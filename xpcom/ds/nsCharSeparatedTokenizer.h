/* -*- Mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef __nsCharSeparatedTokenizer_h
#define __nsCharSeparatedTokenizer_h

#include "mozilla/RangedPtr.h"

#include "nsDependentSubstring.h"
#include "nsCRT.h"

/**
 * This parses a SeparatorChar-separated string into tokens.
 * Whitespace surrounding tokens is not treated as part of tokens, however
 * whitespace inside a token is. If the final token is the empty string, it is
 * not returned.
 *
 * Some examples, with SeparatorChar = ',':
 *
 * "foo, bar, baz" ->      "foo" "bar" "baz"
 * "foo,bar,baz" ->        "foo" "bar" "baz"
 * "foo , bar hi , baz" -> "foo" "bar hi" "baz"
 * "foo, ,bar,baz" ->      "foo" "" "bar" "baz"
 * "foo,,bar,baz" ->       "foo" "" "bar" "baz"
 * "foo,bar,baz," ->       "foo" "bar" "baz"
 *
 * The function used for whitespace detection is a template argument.
 * By default, it is NS_IsAsciiWhitespace.
 */
template<bool IsWhitespace(PRUnichar) = NS_IsAsciiWhitespace>
class nsCharSeparatedTokenizerTemplate
{
public:
    // Flags -- only one for now. If we need more, they should be defined to
    // be 1<<1, 1<<2, etc. (They're masks, and aFlags/mFlags are bitfields.)
    enum {
        SEPARATOR_OPTIONAL = 1
    };

    nsCharSeparatedTokenizerTemplate(const nsSubstring& aSource,
                                     PRUnichar aSeparatorChar,
                                     uint32_t  aFlags = 0)
        : mFirstTokenBeganWithWhitespace(false),
          mLastTokenEndedWithWhitespace(false),
          mLastTokenEndedWithSeparator(false),
          mSeparatorChar(aSeparatorChar),
          mFlags(aFlags),
          mIter(aSource.Data(), aSource.Length()),
          mEnd(aSource.Data() + aSource.Length(), aSource.Data(),
               aSource.Length())
    {
        // Skip initial whitespace
        while (mIter < mEnd && IsWhitespace(*mIter)) {
            mFirstTokenBeganWithWhitespace = true;
            ++mIter;
        }
    }

    /**
     * Checks if any more tokens are available.
     */
    bool hasMoreTokens()
    {
        NS_ASSERTION(mIter == mEnd || !IsWhitespace(*mIter),
                     "Should be at beginning of token if there is one");

        return mIter < mEnd;
    }

    bool firstTokenBeganWithWhitespace() const
    {
        return mFirstTokenBeganWithWhitespace;
    }

    bool lastTokenEndedWithSeparator() const
    {
        return mLastTokenEndedWithSeparator;
    }

    bool lastTokenEndedWithWhitespace() const
    {
        return mLastTokenEndedWithWhitespace;
    }

    /**
     * Returns the next token.
     */
    const nsDependentSubstring nextToken()
    {
        mozilla::RangedPtr<const PRUnichar> tokenStart = mIter, tokenEnd = mIter;

        NS_ASSERTION(mIter == mEnd || !IsWhitespace(*mIter),
                     "Should be at beginning of token if there is one");

        // Search until we hit separator or end (or whitespace, if separator
        // isn't required -- see clause with 'break' below).
        while (mIter < mEnd && *mIter != mSeparatorChar) {
          // Skip to end of current word.
          while (mIter < mEnd &&
                 !IsWhitespace(*mIter) && *mIter != mSeparatorChar) {
              ++mIter;
          }
          tokenEnd = mIter;

          // Skip whitespace after current word.
          mLastTokenEndedWithWhitespace = false;
          while (mIter < mEnd && IsWhitespace(*mIter)) {
              mLastTokenEndedWithWhitespace = true;
              ++mIter;
          }
          if (mFlags & SEPARATOR_OPTIONAL) {
            // We've hit (and skipped) whitespace, and that's sufficient to end
            // our token, regardless of whether we've reached a SeparatorChar.
            break;
          } // (else, we'll keep looping until we hit mEnd or SeparatorChar)
        }

        mLastTokenEndedWithSeparator = (mIter != mEnd &&
                                        *mIter == mSeparatorChar);
        NS_ASSERTION((mFlags & SEPARATOR_OPTIONAL) ||
                     (mLastTokenEndedWithSeparator == (mIter < mEnd)),
                     "If we require a separator and haven't hit the end of "
                     "our string, then we shouldn't have left the loop "
                     "unless we hit a separator");

        // Skip separator (and any whitespace after it), if we're at one.
        if (mLastTokenEndedWithSeparator) {
            ++mIter;

            while (mIter < mEnd && IsWhitespace(*mIter)) {
                ++mIter;
            }
        }

        return Substring(tokenStart.get(), tokenEnd.get());
    }

private:
    mozilla::RangedPtr<const PRUnichar> mIter;
    const mozilla::RangedPtr<const PRUnichar> mEnd;
    bool mFirstTokenBeganWithWhitespace;
    bool mLastTokenEndedWithWhitespace;
    bool mLastTokenEndedWithSeparator;
    PRUnichar mSeparatorChar;
    uint32_t  mFlags;
};

class nsCharSeparatedTokenizer: public nsCharSeparatedTokenizerTemplate<>
{
public:
    nsCharSeparatedTokenizer(const nsSubstring& aSource,
                             PRUnichar aSeparatorChar,
                             uint32_t  aFlags = 0)
      : nsCharSeparatedTokenizerTemplate<>(aSource, aSeparatorChar, aFlags)
    {
    }
};

class nsCCharSeparatedTokenizer
{
public:
    nsCCharSeparatedTokenizer(const nsCSubstring& aSource,
                              char aSeparatorChar)
        : mSeparatorChar(aSeparatorChar),
          mIter(aSource.Data(), aSource.Length()),
          mEnd(aSource.Data() + aSource.Length(), aSource.Data(),
               aSource.Length())
    {

        while (mIter < mEnd && isWhitespace(*mIter)) {
            ++mIter;
        }
    }

    /**
     * Checks if any more tokens are available.
     */
    bool hasMoreTokens()
    {
        return mIter < mEnd;
    }

    /**
     * Returns the next token.
     */
    const nsDependentCSubstring nextToken()
    {
        mozilla::RangedPtr<const char> tokenStart = mIter,tokenEnd = mIter;

        // Search until we hit separator or end.
        while (mIter < mEnd && *mIter != mSeparatorChar) {
          while (mIter < mEnd &&
                 !isWhitespace(*mIter) && *mIter != mSeparatorChar) {
              ++mIter;
          }
          tokenEnd = mIter;

          while (mIter < mEnd && isWhitespace(*mIter)) {
              ++mIter;
          }
        }

        // Skip separator (and any whitespace after it).
        if (mIter < mEnd) {
            NS_ASSERTION(*mIter == mSeparatorChar, "Ended loop too soon");
            ++mIter;

            while (mIter < mEnd && isWhitespace(*mIter)) {
                ++mIter;
            }
        }

        return Substring(tokenStart.get(), tokenEnd.get());
    }

private:
    mozilla::RangedPtr<const char> mIter;
    const mozilla::RangedPtr<const char> mEnd;
    char mSeparatorChar;

    bool isWhitespace(unsigned char aChar)
    {
        return aChar <= ' ' &&
               (aChar == ' ' || aChar == '\n' ||
                aChar == '\r'|| aChar == '\t');
    }
};

#endif /* __nsCharSeparatedTokenizer_h */
