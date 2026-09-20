"""Curated per-level vocabulary lists with pre-written Bangla translations, used to give each
session a small set of target words to naturally work into conversation."""
import random

VOCAB_BANK = {
    "beginner": [
        {"word": "breakfast", "bangla": "সকালের নাস্তা"},
        {"word": "weather", "bangla": "আবহাওয়া"},
        {"word": "expensive", "bangla": "দামী"},
        {"word": "cheap", "bangla": "সস্তা"},
        {"word": "tired", "bangla": "ক্লান্ত"},
        {"word": "hungry", "bangla": "ক্ষুধার্ত"},
        {"word": "comfortable", "bangla": "আরামদায়ক"},
        {"word": "borrow", "bangla": "ধার করা"},
        {"word": "neighbor", "bangla": "প্রতিবেশী"},
        {"word": "appointment", "bangla": "সাক্ষাতের সময়"},
        {"word": "schedule", "bangla": "সময়সূচি"},
        {"word": "grocery", "bangla": "মুদি সামগ্রী"},
        {"word": "traffic", "bangla": "যানজট"},
        {"word": "weekend", "bangla": "সাপ্তাহিক ছুটি"},
        {"word": "furniture", "bangla": "আসবাবপত্র"},
        {"word": "umbrella", "bangla": "ছাতা"},
        {"word": "receipt", "bangla": "রসিদ"},
        {"word": "crowded", "bangla": "ভিড়পূর্ণ"},
        {"word": "nervous", "bangla": "উদ্বিগ্ন"},
        {"word": "exhausted", "bangla": "অবসন্ন"},
    ],
    "intermediate": [
        {"word": "opportunity", "bangla": "সুযোগ"},
        {"word": "achievement", "bangla": "অর্জন"},
        {"word": "convenient", "bangla": "সুবিধাজনক"},
        {"word": "frustrated", "bangla": "হতাশ"},
        {"word": "ambitious", "bangla": "উচ্চাকাঙ্ক্ষী"},
        {"word": "reliable", "bangla": "নির্ভরযোগ্য"},
        {"word": "curious", "bangla": "কৌতূহলী"},
        {"word": "genuine", "bangla": "আন্তরিক"},
        {"word": "overwhelmed", "bangla": "অভিভূত"},
        {"word": "procrastinate", "bangla": "কাজ ফেলে রাখা"},
        {"word": "compromise", "bangla": "আপস করা"},
        {"word": "persuade", "bangla": "রাজি করানো"},
        {"word": "appreciate", "bangla": "কৃতজ্ঞতা জানানো"},
        {"word": "anticipate", "bangla": "প্রত্যাশা করা"},
        {"word": "flexible", "bangla": "নমনীয়"},
        {"word": "consistent", "bangla": "ধারাবাহিক"},
        {"word": "priority", "bangla": "অগ্রাধিকার"},
        {"word": "assumption", "bangla": "অনুমান"},
        {"word": "enthusiastic", "bangla": "উৎসাহী"},
        {"word": "independent", "bangla": "স্বাধীন"},
    ],
    "advanced": [
        {"word": "ambiguous", "bangla": "দ্ব্যর্থক"},
        {"word": "resilient", "bangla": "সহনশীল"},
        {"word": "meticulous", "bangla": "অত্যন্ত যত্নশীল"},
        {"word": "pragmatic", "bangla": "বাস্তববাদী"},
        {"word": "nuance", "bangla": "সূক্ষ্ম পার্থক্য"},
        {"word": "eloquent", "bangla": "বাগ্মী"},
        {"word": "ubiquitous", "bangla": "সর্বব্যাপী"},
        {"word": "skeptical", "bangla": "সংশয়বাদী"},
        {"word": "articulate", "bangla": "স্পষ্টভাষী"},
        {"word": "profound", "bangla": "গভীর"},
        {"word": "discern", "bangla": "বুঝতে পারা"},
        {"word": "contentious", "bangla": "বিতর্কিত"},
        {"word": "arbitrary", "bangla": "যথেচ্ছ"},
        {"word": "inevitable", "bangla": "অনিবার্য"},
        {"word": "subtle", "bangla": "সূক্ষ্ম"},
        {"word": "coherent", "bangla": "সুসংগত"},
        {"word": "indispensable", "bangla": "অপরিহার্য"},
        {"word": "candid", "bangla": "অকপট"},
        {"word": "tenacious", "bangla": "দৃঢ়প্রতিজ্ঞ"},
        {"word": "elusive", "bangla": "দুর্বোধ্য"},
    ],
}

TARGET_WORDS_PER_SESSION = 5
# Vocabulary-focused sessions get more target words, since building vocabulary is the explicit
# point rather than a side effect of conversation.
VOCABULARY_MODE_WORDS_PER_SESSION = 8


def pick_target_words(level: str, practice_mode: str = "general") -> list[dict]:
    bank = VOCAB_BANK.get(level, VOCAB_BANK["intermediate"])
    count = (
        VOCABULARY_MODE_WORDS_PER_SESSION
        if practice_mode == "vocabulary"
        else TARGET_WORDS_PER_SESSION
    )
    return random.sample(bank, min(count, len(bank)))
