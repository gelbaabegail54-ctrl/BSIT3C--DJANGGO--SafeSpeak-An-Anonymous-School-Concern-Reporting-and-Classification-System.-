"""Dependency-free NLP classification for SafeSpeak.

The engine stays entirely on the server: report text is tokenized locally and
scored against category keywords. It returns a confidence score and the
keywords that influenced the prediction so administrators can review it.
"""

from dataclasses import dataclass, field
import re


LOW_CONFIDENCE_THRESHOLD = 55

DEFAULT_CATEGORY_KEYWORDS = {
    'Bullying': (
        'bully*', 'bullied', 'bullying', 'bullies', 'harass*', 'threat*',
        'intimidat*', 'fight*', 'violen*', 'name-calling', 'cyberbully*',
        'teas*', 'mock*', 'exclusion', 'rumor*',
    ),
    'Safety': (
        'safety', 'unsafe', 'danger*', 'fire', 'accident*', 'injur*', 'weapon*',
        'emergency', 'hazard*', 'flood*', 'earthquake', 'lockdown', 'stranger*',
    ),
    'Facilities': (
        'facility', 'facilities', 'broken', 'damage*', 'classroom*', 'building*',
        'restroom*', 'canteen*', 'cafeteria*', 'chair*', 'desk*', 'electric*',
        'water', 'leak*', 'aircon*', 'fan*', 'light*', 'roof*', 'sink*', 'toilet*',
        'plumb*', 'projector*',
    ),
    'Academic': (
        'academic*', 'grade*', 'teacher*', 'class', 'exam*', 'assignment*',
        'lesson*', 'curriculum*', 'subject*', 'homework*', 'deadline*',
        'cheat*', 'plagiar*', 'schedule*', 'module*',
    ),
    'Personal': (
        'personal*', 'family', 'friend*', 'stress*', 'mental', 'emotional*',
        'relationship*', 'depress*', 'anxiety', 'anxious', 'lonely', 'homesick*',
        'grief*', 'self-esteem',
    ),
}

DEFAULT_CATEGORY_DESCRIPTIONS = {
    'Bullying': 'Harassment, threats, intimidation, and other harmful behavior.',
    'Safety': 'Immediate safety risks, hazards, and emergency-related concerns.',
    'Facilities': 'Buildings, equipment, utilities, and campus maintenance issues.',
    'Academic': 'Classes, grades, requirements, teaching, and schoolwork.',
    'Personal': 'Emotional well-being, relationships, and personal challenges.',
}

CATEGORY_PRIORITY = {
    'Safety': 0,
    'Bullying': 1,
    'Personal': 2,
    'Facilities': 3,
    'Academic': 4,
}

TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class CategoryProfile:
    """A category and the keywords the classifier will look for."""

    category: object
    keywords: tuple


@dataclass
class CategoryScore:
    """The accumulated score for one category."""

    name: str
    score: float
    hits: list = field(default_factory=list)
    share: int = 0


@dataclass
class ClassificationResult:
    """The outcome of classifying a piece of text."""

    category: object | None
    confidence: int
    signals: list
    scores: list

    @property
    def suggested_name(self):
        return self.category.name if self.category is not None else 'General'

    @property
    def matched(self):
        return self.category is not None


def normalize_text(text):
    """Lowercase text and collapse punctuation into clean word boundaries."""
    if not text:
        return ''
    value = str(text).lower()
    value = value.replace('\u2019', "'").replace('\u2018', "'")
    value = re.sub(r'[^a-z0-9\']+', ' ', value)
    return ' '.join(value.split())


def tokenize(text):
    """Split normalized text into searchable tokens."""
    return TOKEN_PATTERN.findall(normalize_text(text))


def parse_keywords(raw_keywords):
    """Turn a comma/newline separated string into a clean keyword list."""
    if not raw_keywords:
        return []
    if isinstance(raw_keywords, (list, tuple)):
        items = raw_keywords
    else:
        items = re.split(r'[,\n;]+', str(raw_keywords))

    keywords = []
    for item in items:
        keyword = ' '.join(str(item).lower().strip().split())
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def default_keywords(name):
    """Return the built-in keyword set for a category name, if one exists."""
    target = str(name).strip().lower()
    for category_name, keywords in DEFAULT_CATEGORY_KEYWORDS.items():
        if category_name.lower() == target:
            return list(keywords)
    return []


def default_description(name):
    """Return the built-in description for a category name."""
    target = str(name).strip().lower()
    for category_name, description in DEFAULT_CATEGORY_DESCRIPTIONS.items():
        if category_name.lower() == target:
            return description
    return ''


def _build_profiles(categories=None):
    """Build category profiles from database categories or built-in defaults."""
    from .models import Category

    if categories is None:
        categories = list(Category.objects.filter(is_active=True))
    else:
        categories = [
            category
            for category in categories
            if getattr(category, 'is_active', True)
        ]

    profiles = []
    for category in categories:
        keywords = parse_keywords(getattr(category, 'keywords', ''))
        if not keywords:
            keywords = default_keywords(category.name)
        if not keywords:
            if str(category.name).strip().lower() == 'general':
                continue
            keywords = [str(category.name).strip().lower()]
        profiles.append(CategoryProfile(category=category, keywords=tuple(keywords)))

    # A fresh installation has no categories yet. Use the built-in model until
    # an administrator creates or seeds the category library.
    if not categories:
        for name, keywords in DEFAULT_CATEGORY_KEYWORDS.items():
            category = Category(
                name=name,
                description=default_description(name),
                keywords=', '.join(keywords),
            )
            profiles.append(CategoryProfile(category=category, keywords=tuple(keywords)))

    return profiles


def _keyword_weight(keyword):
    """Give longer words and phrases more influence than short generic terms."""
    word_count = len(keyword.split())
    weight = 1.0 + min(len(keyword.replace('*', '')), 10) * 0.25
    if word_count > 1:
        weight += 0.75 * (word_count - 1)
    return weight


def _keyword_hits(tokens, keyword):
    """Count exact, prefix, or phrase matches for one keyword."""
    parts = keyword.split()

    if len(parts) > 1:
        if keyword.endswith('*'):
            fixed = parts[:-1]
            stem = parts[-1][:-1]
            if not stem:
                return 0
            width = len(parts)
            hits = 0
            for index in range(len(tokens) - width + 1):
                if tuple(tokens[index:index + len(fixed)]) != tuple(fixed):
                    continue
                if tokens[index + len(fixed)].startswith(stem):
                    hits += 1
            return hits

        width = len(parts)
        return sum(
            1
            for index in range(len(tokens) - width + 1)
            if tuple(tokens[index:index + width]) == tuple(parts)
        )

    wildcard = keyword.endswith('*')
    target = keyword[:-1] if wildcard else keyword
    if not target:
        return 0
    if wildcard:
        return sum(1 for token in tokens if token.startswith(target))
    return sum(1 for token in tokens if token == target)


def classify_text(text, categories=None):
    """Classify text and return the best category, confidence, and signals."""
    tokens = tokenize(text)
    if not tokens:
        return ClassificationResult(None, 0, [], [])

    profiles = _build_profiles(categories)
    scores = []
    for profile in profiles:
        total = 0.0
        hits = []
        for keyword in profile.keywords:
            match_count = _keyword_hits(tokens, keyword)
            if not match_count:
                continue
            total += _keyword_weight(keyword) + 0.2 * min(match_count - 1, 4)
            label = keyword.rstrip('*').strip()
            if label and label not in hits:
                hits.append(label)
        if total > 0:
            scores.append(CategoryScore(profile.category.name, round(total, 2), hits))

    if not scores:
        return ClassificationResult(None, 0, [], [])

    scores.sort(
        key=lambda item: (
            -item.score,
            CATEGORY_PRIORITY.get(item.name, 99),
            item.name.lower(),
        )
    )
    best = scores[0]
    total_score = sum(item.score for item in scores) or 1
    dominance = best.score / total_score
    coverage = min(best.score / 8.0, 1.0)
    confidence = round(100 * (0.4 * dominance + 0.6 * coverage))
    confidence = max(1, min(confidence, 99))

    for item in scores:
        item.share = round(item.score / total_score * 100)

    best_category = next(
        profile.category for profile in profiles
        if profile.category.name == best.name
    )
    return ClassificationResult(
        category=best_category,
        confidence=confidence,
        signals=best.hits[:8],
        scores=scores,
    )
