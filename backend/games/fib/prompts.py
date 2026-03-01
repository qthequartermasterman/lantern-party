"""
Original trivia prompts for Fib.

Each prompt has a blank ("_____") where the true answer goes.
Players invent fake answers; everyone votes for the real one.
All facts are original research – no reproduction of proprietary question databases.
"""
from __future__ import annotations

# Each item: {"prompt": str, "truth": str, "category": str}
ROUND_PROMPTS: list[dict[str, str]] = [
    {
        "prompt": "The national animal of Scotland is the _____.",
        "truth": "unicorn",
        "category": "World Trivia",
    },
    {
        "prompt": "A day on _____ is longer than its year.",
        "truth": "Venus",
        "category": "Space",
    },
    {
        "prompt": "Oxford University started teaching before the _____ Empire was founded.",
        "truth": "Aztec",
        "category": "History",
    },
    {
        "prompt": "The dot above a lowercase 'i' or 'j' is called a _____.",
        "truth": "tittle",
        "category": "Language",
    },
    {
        "prompt": "Botanically speaking, bananas are classified as _____.",
        "truth": "berries",
        "category": "Science",
    },
    {
        "prompt": "Sharks are older than _____ – they appeared millions of years earlier.",
        "truth": "trees",
        "category": "Nature",
    },
    {
        "prompt": "A group of flamingos is called a _____.",
        "truth": "flamboyance",
        "category": "Nature",
    },
    {
        "prompt": "Honey found in ancient Egyptian _____ was still perfectly edible after 3,000 years.",
        "truth": "tombs",
        "category": "History",
    },
    {
        "prompt": "The word 'salary' comes from the Latin word for _____.",
        "truth": "salt",
        "category": "Language",
    },
    {
        "prompt": "An ostrich's eye is bigger than its _____.",
        "truth": "brain",
        "category": "Nature",
    },
    {
        "prompt": "Butterflies taste things with their _____.",
        "truth": "feet",
        "category": "Nature",
    },
    {
        "prompt": "A flock of crows is called a _____.",
        "truth": "murder",
        "category": "Nature",
    },
    {
        "prompt": "Nintendo was originally founded in 1889 as a _____ company.",
        "truth": "playing card",
        "category": "Pop Culture",
    },
    {
        "prompt": "Cleopatra lived closer in time to the _____ than to the construction of the Great Pyramid.",
        "truth": "Moon landing",
        "category": "History",
    },
    {
        "prompt": "The Anglo-Zanzibar War of 1896 is the shortest war in history, lasting only _____ minutes.",
        "truth": "38",
        "category": "History",
    },
    {
        "prompt": "The average person produces enough saliva in their lifetime to fill _____ swimming pools.",
        "truth": "two",
        "category": "Human Body",
    },
    {
        "prompt": "Wombat droppings are uniquely cube-shaped to prevent them rolling off _____.",
        "truth": "rocks",
        "category": "Nature",
    },
    {
        "prompt": "A group of owls is called a _____.",
        "truth": "parliament",
        "category": "Nature",
    },
    {
        "prompt": "The word 'robot' was first used in a 1920 play by Czech author _____.",
        "truth": "Karel Čapek",
        "category": "Language",
    },
    {
        "prompt": "Technically, the Great Wall of China is _____ from space with the naked eye.",
        "truth": "not visible",
        "category": "World Trivia",
    },
    {
        "prompt": "A group of cats is called a _____.",
        "truth": "clowder",
        "category": "Nature",
    },
    {
        "prompt": "It is physically impossible to hum while holding your _____.",
        "truth": "nose",
        "category": "Human Body",
    },
    {
        "prompt": "Polar bear fur is actually _____, not white.",
        "truth": "transparent",
        "category": "Nature",
    },
    {
        "prompt": "A shrimp's heart is located in its _____.",
        "truth": "head",
        "category": "Nature",
    },
    {
        "prompt": "The king of hearts is the only king in a standard deck of cards with no _____.",
        "truth": "mustache",
        "category": "Pop Culture",
    },
    {
        "prompt": "Cows produce more milk when listening to _____.",
        "truth": "slow music",
        "category": "Science",
    },
    {
        "prompt": "The longest hiccupping episode on record lasted _____ years.",
        "truth": "68",
        "category": "Human Body",
    },
    {
        "prompt": "There are more possible iterations of a game of chess than there are _____ in the observable universe.",
        "truth": "atoms",
        "category": "Science",
    },
    {
        "prompt": "Sea otters hold hands while sleeping so they don't _____.",
        "truth": "drift apart",
        "category": "Nature",
    },
    {
        "prompt": "The first alarm clock could only ring at _____.",
        "truth": "4 a.m.",
        "category": "History",
    },
    {
        "prompt": "A group of pugs is called a _____.",
        "truth": "grumble",
        "category": "Nature",
    },
    {
        "prompt": "The average cloud weighs about _____ pounds.",
        "truth": "1.1 million",
        "category": "Science",
    },
    {
        "prompt": "Octopuses have _____ hearts.",
        "truth": "three",
        "category": "Nature",
    },
    {
        "prompt": "The ancient Romans used _____ as a mouthwash.",
        "truth": "urine",
        "category": "History",
    },
    {
        "prompt": "The first webcam was invented to monitor a _____ pot at Cambridge University.",
        "truth": "coffee",
        "category": "Tech",
    },
]

FINAL_PROMPTS: list[dict[str, str]] = [
    {
        "prompt": "The shortest complete sentence in the English language is '_____.'",
        "truth": "I am",
        "category": "Language",
    },
    {
        "prompt": "It takes a photon about _____ years to travel from the core of the Sun to its surface.",
        "truth": "100,000",
        "category": "Space",
    },
    {
        "prompt": "The inventor of the Pringles can was buried in one after he died – his family fulfilled his wish that his ashes be placed inside _____.",
        "truth": "a Pringles can",
        "category": "Pop Culture",
    },
    {
        "prompt": "Male platypuses have venomous spurs on their _____ that can cause excruciating pain in humans.",
        "truth": "hind legs",
        "category": "Nature",
    },
    {
        "prompt": "Humans share about 50% of their DNA with _____.",
        "truth": "bananas",
        "category": "Science",
    },
]

# Generic lies used when the game must generate an answer for a player
LIE_BANK: list[str] = [
    "The number seventeen",
    "A type of cheese",
    "The moon",
    "Florida",
    "Napoleon",
    "With their feet",
    "By accident",
    "A large mushroom",
    "The letter Q",
    "1847",
    "Three times a year",
    "Only in winter",
    "A small purple fish",
    "The word 'ennui'",
    "Exactly 42",
    "Belgium",
    "1066",
    "A golden retriever",
    "Sir Francis Drake",
    "The colour mauve",
]
