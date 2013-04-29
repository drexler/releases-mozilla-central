# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from WebIDL import IDLInterface, IDLExternalInterface
import os

autogenerated_comment = "/* THIS FILE IS AUTOGENERATED - DO NOT EDIT */\n"

class Configuration:
    """
    Represents global configuration state based on IDL parse data and
    the configuration file.
    """
    def __init__(self, filename, parseData):

        # Read the configuration file.
        glbl = {}
        execfile(filename, glbl)
        config = glbl['DOMInterfaces']

        # Build descriptors for all the interfaces we have in the parse data.
        # This allows callers to specify a subset of interfaces by filtering
        # |parseData|.
        self.descriptors = []
        self.interfaces = {}
        self.maxProtoChainLength = 0;
        for thing in parseData:
            # Some toplevel things are sadly types, and those have an
            # isInterface that doesn't mean the same thing as IDLObject's
            # isInterface()...
            if (not isinstance(thing, IDLInterface) and
                not isinstance(thing, IDLExternalInterface)):
                continue
            iface = thing
            self.interfaces[iface.identifier.name] = iface
            if iface.identifier.name not in config:
                # Completely skip consequential interfaces with no descriptor
                # if they have no interface object because chances are we
                # don't need to do anything interesting with them.
                if iface.isConsequential() and not iface.hasInterfaceObject():
                    continue
                entry = {}
            else:
                entry = config[iface.identifier.name]
            if not isinstance(entry, list):
                assert isinstance(entry, dict)
                entry = [entry]
            elif len(entry) == 1 and entry[0].get("workers", False):
                # List with only a workers descriptor means we should
                # infer a mainthread descriptor.  If you want only
                # workers bindings, don't use a list here.
                entry.append({})
            self.descriptors.extend([Descriptor(self, iface, x) for x in entry])

        # Mark the descriptors for which the nativeType corresponds to exactly
        # one interface.
        for descriptor in self.descriptors:
            descriptor.unsharedImplementation = all(
                d.nativeType != descriptor.nativeType or d == descriptor
                for d in self.descriptors)

        self.enums = [e for e in parseData if e.isEnum()]

        # Figure out what our main-thread and worker dictionaries and callbacks
        # are.
        mainTypes = set()
        for descriptor in ([self.getDescriptor("DummyInterface", workers=False)] +
                           self.getDescriptors(workers=False, isExternal=False, skipGen=False)):
            mainTypes |= set(getFlatTypes(getTypesFromDescriptor(descriptor)))
        (mainCallbacks, mainDictionaries) = findCallbacksAndDictionaries(mainTypes)

        workerTypes = set();
        for descriptor in ([self.getDescriptor("DummyInterfaceWorkers", workers=True)] +
                           self.getDescriptors(workers=True, isExternal=False, skipGen=False)):
            workerTypes |= set(getFlatTypes(getTypesFromDescriptor(descriptor)))
        (workerCallbacks, workerDictionaries) = findCallbacksAndDictionaries(workerTypes)

        self.dictionaries = [d for d in parseData if d.isDictionary()]
        self.callbacks = [c for c in parseData if
                          c.isCallback() and not c.isInterface()]

        def flagWorkerOrMainThread(items, main, worker):
            for item in items:
                if item in main:
                    item.setUserData("mainThread", True)
                if item in worker:
                    item.setUserData("workers", True)
        flagWorkerOrMainThread(self.dictionaries, mainDictionaries,
                               workerDictionaries);
        flagWorkerOrMainThread(self.callbacks, mainCallbacks, workerCallbacks)

        # Keep the descriptor list sorted for determinism.
        self.descriptors.sort(lambda x,y: cmp(x.name, y.name))

    def getInterface(self, ifname):
        return self.interfaces[ifname]
    def getDescriptors(self, **filters):
        """Gets the descriptors that match the given filters."""
        curr = self.descriptors
        for key, val in filters.iteritems():
            if key == 'webIDLFile':
                getter = lambda x: x.interface.filename()
            elif key == 'hasInterfaceObject':
                getter = lambda x: (not x.interface.isExternal() and
                                    x.interface.hasInterfaceObject())
            elif key == 'hasInterfacePrototypeObject':
                getter = lambda x: (not x.interface.isExternal() and
                                    x.interface.hasInterfacePrototypeObject())
            elif key == 'hasInterfaceOrInterfacePrototypeObject':
                getter = lambda x: x.hasInterfaceOrInterfacePrototypeObject()
            elif key == 'isCallback':
                getter = lambda x: x.interface.isCallback()
            elif key == 'isExternal':
                getter = lambda x: x.interface.isExternal()
            elif key == 'isJSImplemented':
                getter = lambda x: x.interface.isJSImplemented()
            else:
                getter = lambda x: getattr(x, key)
            curr = filter(lambda x: getter(x) == val, curr)
        return curr
    def getEnums(self, webIDLFile):
        return filter(lambda e: e.filename() == webIDLFile, self.enums)

    @staticmethod
    def _filterForFileAndWorkers(items, filters):
        """Gets the items that match the given filters."""
        for key, val in filters.iteritems():
            if key == 'webIDLFile':
                items = filter(lambda x: x.filename() == val, items)
            elif key == 'workers':
                if val:
                    items = filter(lambda x: x.getUserData("workers", False), items)
                else:
                    items = filter(lambda x: x.getUserData("mainThread", False), items)
            else:
                assert(0) # Unknown key
        return items
    def getDictionaries(self, **filters):
        return self._filterForFileAndWorkers(self.dictionaries, filters)
    def getCallbacks(self, **filters):
        return self._filterForFileAndWorkers(self.callbacks, filters)

    def getDescriptor(self, interfaceName, workers):
        """
        Gets the appropriate descriptor for the given interface name
        and the given workers boolean.
        """
        iface = self.getInterface(interfaceName)
        descriptors = self.getDescriptors(interface=iface)

        # The only filter we currently have is workers vs non-workers.
        matches = filter(lambda x: x.workers is workers, descriptors)

        # After filtering, we should have exactly one result.
        if len(matches) is not 1:
            raise NoSuchDescriptorError("For " + interfaceName + " found " +
                                        str(len(matches)) + " matches");
        return matches[0]
    def getDescriptorProvider(self, workers):
        """
        Gets a descriptor provider that can provide descriptors as needed,
        for the given workers boolean
        """
        return DescriptorProvider(self, workers)

class NoSuchDescriptorError(TypeError):
    def __init__(self, str):
        TypeError.__init__(self, str)

class DescriptorProvider:
    """
    A way of getting descriptors for interface names
    """
    def __init__(self, config, workers):
        self.config = config
        self.workers = workers

    def getDescriptor(self, interfaceName):
        """
        Gets the appropriate descriptor for the given interface name given the
        context of the current descriptor. This selects the appropriate
        implementation for cases like workers.
        """
        return self.config.getDescriptor(interfaceName, self.workers)

class Descriptor(DescriptorProvider):
    """
    Represents a single descriptor for an interface. See Bindings.conf.
    """
    def __init__(self, config, interface, desc):
        DescriptorProvider.__init__(self, config, desc.get('workers', False))
        self.interface = interface

        # Read the desc, and fill in the relevant defaults.
        ifaceName = self.interface.identifier.name
        if self.interface.isExternal():
            if self.workers:
                nativeTypeDefault = "JSObject"
            else:
                nativeTypeDefault = "nsIDOM" + ifaceName
        elif self.interface.isCallback():
            if self.workers:
                nativeTypeDefault = "JSObject"
            else:
                nativeTypeDefault = "mozilla::dom::" + ifaceName
        else:
            if self.workers:
                nativeTypeDefault = "mozilla::dom::workers::" + ifaceName
            else:
                nativeTypeDefault = "mozilla::dom::" + ifaceName

        self.nativeType = desc.get('nativeType', nativeTypeDefault)
        self.jsImplParent = desc.get('jsImplParent', self.nativeType)

        # Do something sane for JSObject
        if self.nativeType == "JSObject":
            headerDefault = "jsapi.h"
        elif self.interface.isCallback() or self.interface.isJSImplemented():
            # A copy of CGHeaders.getDeclarationFilename; we can't
            # import it here, sadly.
            # Use our local version of the header, not the exported one, so that
            # test bindings, which don't export, will work correctly.
            basename = os.path.basename(self.interface.filename())
            headerDefault = basename.replace('.webidl', 'Binding.h')
        else:
            if self.workers:
                headerDefault = "mozilla/dom/workers/bindings/%s.h" % ifaceName
            elif not self.interface.isExternal() and self.interface.getExtendedAttribute("HeaderFile"):
                headerDefault = self.interface.getExtendedAttribute("HeaderFile")[0]
            else:
                headerDefault = self.nativeType
                headerDefault = headerDefault.replace("::", "/") + ".h"
        self.headerFile = desc.get('headerFile', headerDefault)
        if self.jsImplParent == self.nativeType:
            self.jsImplParentHeader = self.headerFile
        else:
            self.jsImplParentHeader = self.jsImplParent.replace("::", "/") + ".h"

        self.skipGen = desc.get('skipGen', False)

        self.notflattened = desc.get('notflattened', False)
        self.register = desc.get('register', True)

        self.hasXPConnectImpls = desc.get('hasXPConnectImpls', False)

        # If we're concrete, we need to crawl our ancestor interfaces and mark
        # them as having a concrete descendant.
        self.concrete = (not self.interface.isExternal() and
                         not self.interface.isCallback() and
                         desc.get('concrete', True))
        operations = {
            'IndexedGetter': None,
            'IndexedSetter': None,
            'IndexedCreator': None,
            'IndexedDeleter': None,
            'NamedGetter': None,
            'NamedSetter': None,
            'NamedCreator': None,
            'NamedDeleter': None,
            'Stringifier': None,
            'LegacyCaller': None
            }
        if self.concrete:
            self.proxy = False
            iface = self.interface
            def addOperation(operation, m):
                if not operations[operation]:
                    operations[operation] = m
            # Since stringifiers go on the prototype, we only need to worry
            # about our own stringifier, not those of our ancestor interfaces.
            for m in iface.members:
                if m.isMethod() and m.isStringifier():
                    addOperation('Stringifier', m)
                # Don't worry about inheriting legacycallers either: in
                # practice these are on most-derived prototypes.
                if m.isMethod() and m.isLegacycaller():
                    if not m.isIdentifierLess():
                        raise TypeError("We don't support legacycaller with "
                                        "identifier.\n%s" % m.location);
                    if len(m.signatures()) != 1:
                        raise TypeError("We don't support overloaded "
                                        "legacycaller.\n%s" % m.location)
                    addOperation('LegacyCaller', m)
            while iface:
                for m in iface.members:
                    if not m.isMethod():
                        continue

                    def addIndexedOrNamedOperation(operation, m):
                        self.proxy = True
                        if m.isIndexed():
                            operation = 'Indexed' + operation
                        else:
                            assert m.isNamed()
                            operation = 'Named' + operation
                        addOperation(operation, m)

                    if m.isGetter():
                        addIndexedOrNamedOperation('Getter', m)
                    if m.isSetter():
                        addIndexedOrNamedOperation('Setter', m)
                    if m.isCreator():
                        addIndexedOrNamedOperation('Creator', m)
                    if m.isDeleter():
                        addIndexedOrNamedOperation('Deleter', m)
                    if m.isLegacycaller() and iface != self.interface:
                        raise TypeError("We don't support legacycaller on "
                                        "non-leaf interface %s.\n%s" %
                                        (iface, iface.location))

                iface.setUserData('hasConcreteDescendant', True)
                iface = iface.parent

            if self.proxy:
                if (not operations['IndexedGetter'] and
                    (operations['IndexedSetter'] or
                     operations['IndexedDeleter'] or
                     operations['IndexedCreator'])):
                    raise SyntaxError("%s supports indexed properties but does "
                                      "not have an indexed getter.\n%s" %
                                      (self.interface, self.interface.location))
                if (not operations['NamedGetter'] and
                    (operations['NamedSetter'] or
                     operations['NamedDeleter'] or
                     operations['NamedCreator'])):
                    raise SyntaxError("%s supports named properties but does "
                                      "not have a named getter.\n%s" %
                                      (self.interface, self.interface.location))
                if operations['LegacyCaller']:
                    raise SyntaxError("%s has a legacy caller but is a proxy; "
                                      "we don't support that yet.\n%s" %
                                      (self.interface, self.interface.location))
                iface = self.interface
                while iface:
                    iface.setUserData('hasProxyDescendant', True)
                    iface = iface.parent
        self.operations = operations

        if self.workers:
            if desc.get('nativeOwnership', 'worker') != 'worker':
                raise TypeError("Worker descriptor for %s should have 'worker' "
                                "as value for nativeOwnership" %
                                self.interface.identifier.name)
            self.nativeOwnership = "worker"
        else:
            self.nativeOwnership = desc.get('nativeOwnership', 'nsisupports')
            if not self.nativeOwnership in ['owned', 'refcounted', 'nsisupports']:
                raise TypeError("Descriptor for %s has unrecognized value (%s) "
                                "for nativeOwnership" %
                                (self.interface.identifier.name, self.nativeOwnership))
        self.customTrace = desc.get('customTrace', self.workers)
        self.customFinalize = desc.get('customFinalize', self.workers)
        self.wrapperCache = (not self.interface.isCallback() and
                             (self.workers or
                              (self.nativeOwnership != 'owned' and
                               desc.get('wrapperCache', True))))

        def make_name(name):
            return name + "_workers" if self.workers else name
        self.name = make_name(interface.identifier.name)

        # self.extendedAttributes is a dict of dicts, keyed on
        # all/getterOnly/setterOnly and then on member name. Values are an
        # array of extended attributes.
        self.extendedAttributes = { 'all': {}, 'getterOnly': {}, 'setterOnly': {} }

        def addExtendedAttribute(attribute, config):
            def add(key, members, attribute):
                for member in members:
                    self.extendedAttributes[key].setdefault(member, []).append(attribute)

            if isinstance(config, dict):
                for key in ['all', 'getterOnly', 'setterOnly']:
                    add(key, config.get(key, []), attribute)
            elif isinstance(config, list):
                add('all', config, attribute)
            else:
                assert isinstance(config, str)
                if config == '*':
                    iface = self.interface
                    while iface:
                        add('all', map(lambda m: m.name, iface.members), attribute)
                        iface = iface.parent
                else:
                    add('all', [config], attribute)

        if self.interface.isJSImplemented():
            addExtendedAttribute('implicitJSContext', ['constructor'])
        else:
            for attribute in ['implicitJSContext', 'resultNotAddRefed']:
                addExtendedAttribute(attribute, desc.get(attribute, {}))

        self.binaryNames = desc.get('binaryNames', {})
        if '__legacycaller' not in self.binaryNames:
            self.binaryNames["__legacycaller"] = "LegacyCall"
        if '__stringifier' not in self.binaryNames:
            self.binaryNames["__stringifier"] = "Stringify"

        # Build the prototype chain.
        self.prototypeChain = []
        parent = interface
        while parent:
            self.prototypeChain.insert(0, make_name(parent.identifier.name))
            parent = parent.parent
        config.maxProtoChainLength = max(config.maxProtoChainLength,
                                         len(self.prototypeChain))

    def hasInterfaceOrInterfacePrototypeObject(self):

        # Forward-declared interfaces don't need either interface object or
        # interface prototype object as they're going to use QI (on main thread)
        # or be passed as a JSObject (on worker threads).
        if self.interface.isExternal():
            return False

        return self.interface.hasInterfaceObject() or self.interface.hasInterfacePrototypeObject()

    def getExtendedAttributes(self, member, getter=False, setter=False):
        def ensureValidThrowsExtendedAttribute(attr):
            assert(attr is None or attr is True or len(attr) == 1)
            if (attr is not None and attr is not True and
                'Workers' not in attr and 'MainThread' not in attr):
                raise TypeError("Unknown value for 'Throws': " + attr[0])

        def maybeAppendInfallibleToAttrs(attrs, throws):
            ensureValidThrowsExtendedAttribute(throws)
            if (throws is None or
                (throws is not True and
                 ('Workers' not in throws or not self.workers) and
                 ('MainThread' not in throws or self.workers))):
                attrs.append("infallible")

        name = member.identifier.name
        throws = self.interface.isJSImplemented() or member.getExtendedAttribute("Throws")
        if member.isMethod():
            attrs = self.extendedAttributes['all'].get(name, [])
            maybeAppendInfallibleToAttrs(attrs, throws)
            return attrs

        assert member.isAttr()
        assert bool(getter) != bool(setter)
        key = 'getterOnly' if getter else 'setterOnly'
        attrs = self.extendedAttributes['all'].get(name, []) + self.extendedAttributes[key].get(name, [])
        if throws is None:
            throwsAttr = "GetterThrows" if getter else "SetterThrows"
            throws = member.getExtendedAttribute(throwsAttr)
        maybeAppendInfallibleToAttrs(attrs, throws)
        return attrs

    def supportsIndexedProperties(self):
        return self.operations['IndexedGetter'] is not None

    def supportsNamedProperties(self):
        return self.operations['NamedGetter'] is not None

    def needsConstructHookHolder(self):
        assert self.interface.hasInterfaceObject()
        return False

    def needsHeaderInclude(self):
        """
        An interface doesn't need a header file if it is not concrete,
        not pref-controlled, and has only consts.
        """
        return (self.interface.isExternal() or self.concrete or
            self.interface.getExtendedAttribute("PrefControlled") or
            self.interface.hasInterfacePrototypeObject())

# Some utility methods
def getTypesFromDescriptor(descriptor):
    """
    Get all argument and return types for all members of the descriptor
    """
    members = [m for m in descriptor.interface.members]
    if descriptor.interface.ctor():
        members.append(descriptor.interface.ctor())
    members.extend(descriptor.interface.namedConstructors)
    signatures = [s for m in members if m.isMethod() for s in m.signatures()]
    types = []
    for s in signatures:
        assert len(s) == 2
        (returnType, arguments) = s
        types.append(returnType)
        types.extend(a.type for a in arguments)

    types.extend(a.type for a in members if a.isAttr())
    return types

def getFlatTypes(types):
    retval = set()
    for type in types:
        type = type.unroll()
        if type.isUnion():
            retval |= set(type.flatMemberTypes)
        else:
            retval.add(type)
    return retval

def getTypesFromDictionary(dictionary):
    """
    Get all member types for this dictionary
    """
    types = []
    curDict = dictionary
    while curDict:
        types.extend([m.type for m in curDict.members])
        curDict = curDict.parent
    return types

def getTypesFromCallback(callback):
    """
    Get the types this callback depends on: its return type and the
    types of its arguments.
    """
    sig = callback.signatures()[0]
    types = [sig[0]] # Return type
    types.extend(arg.type for arg in sig[1]) # Arguments
    return types

def findCallbacksAndDictionaries(inputTypes):
    """
    Ensure that all callbacks and dictionaries reachable from types end up in
    the returned callbacks and dictionaries sets.

    Note that we assume that our initial invocation already includes all types
    reachable via descriptors in "types", so we only have to deal with things
    that are themeselves reachable via callbacks and dictionaries.
    """
    def doFindCallbacksAndDictionaries(types, callbacks, dictionaries):
        unhandledTypes = set()
        for type in types:
            if type.isCallback() and type not in callbacks:
                unhandledTypes |= getFlatTypes(getTypesFromCallback(type))
                callbacks.add(type)
            elif type.isDictionary() and type.inner not in dictionaries:
                d = type.inner
                unhandledTypes |= getFlatTypes(getTypesFromDictionary(d))
                while d:
                    dictionaries.add(d)
                    d = d.parent
        if len(unhandledTypes) != 0:
            doFindCallbacksAndDictionaries(unhandledTypes, callbacks, dictionaries)

    retCallbacks = set()
    retDictionaries = set()
    doFindCallbacksAndDictionaries(inputTypes, retCallbacks, retDictionaries)
    return (retCallbacks, retDictionaries)
