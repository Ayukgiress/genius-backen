import asyncio
import json
import os
import re
import logging
from datetime import datetime
from typing import List, Optional, Dict, Set, Tuple
import httpx

from app.schemas.job import JobCreate, JobMatchResponse

logger = logging.getLogger(__name__)


# =============================================================================
# Skill dictionary & aliases
# =============================================================================
#
# Why this exists: the previous `extract_skills_from_text` did raw `in` substring
# checks against a flat set of ~60 skills. That had three problems:
#   1. "Go" falsely matched every occurrence of the word "go"
#   2. It missed aliases ("Postgres" vs "PostgreSQL", "ReactJS" vs "React")
#   3. It matched "c" inside almost any word containing the letter c
#
# The fix: a small canonical-skill -> alias map, plus a word-boundary regex
# (with care for multi-word skills like "machine learning"), and an explicit
# stop-word exclusion for the worst false positive (the word "go").
#
SKILL_ALIASES: Dict[str, Set[str]] = {
    # Languages
    "python": {"python", "python3", "py"},
    "javascript": {"javascript", "js", "es6", "es2015"},
    "typescript": {"typescript", "ts"},
    "java": {"java"},
    "go": {"golang"},
    "rust": {"rust", "rustlang"},
    "c++": {"c++", "cpp", "cplusplus"},
    "c#": {"c#", "csharp", "c-sharp"},
    "c": {"ansi c", "gnu c"},
    "php": {"php", "php7", "php8"},
    "ruby": {"ruby", "ruby on rails", "rails"},
    "swift": {"swift", "swiftui"},
    "kotlin": {"kotlin"},
    "scala": {"scala"},
    "sql": {"sql", "tsql", "plsql"},
    "html": {"html", "html5"},
    "css": {"css", "css3", "sass", "scss", "less"},
    # Frontend frameworks
    "react": {"react", "reactjs", "react.js", "next.js", "nextjs"},
    "vue": {"vue", "vuejs", "vue.js", "nuxt"},
    "angular": {"angular", "angularjs"},
    "svelte": {"svelte", "sveltekit"},
    # Backend frameworks
    "node.js": {"nodejs", "node.js", "express.js", "expressjs", "nestjs"},
    "django": {"django"},
    "flask": {"flask"},
    "fastapi": {"fastapi", "fast api"},
    "spring": {"spring", "spring boot", "springboot"},
    "laravel": {"laravel"},
    ".net": {".net", "dotnet", "asp.net", "aspnet"},
    # Cloud & DevOps
    "aws": {"aws", "amazon web services", "ec2", "s3", "lambda"},
    "gcp": {"gcp", "google cloud", "google cloud platform"},
    "azure": {"azure", "microsoft azure"},
    "docker": {"docker", "dockerfile", "docker-compose"},
    "kubernetes": {"kubernetes", "k8s"},
    "terraform": {"terraform", " tf "},
    "ansible": {"ansible"},
    "jenkins": {"jenkins"},
    "github actions": {"github actions", "gh actions"},
    "ci/cd": {"ci/cd", "ci cd", "continuous integration", "continuous deployment"},
    # Databases
    "postgresql": {"postgresql", "postgres", "psql"},
    "mysql": {"mysql", "mariadb"},
    "mongodb": {"mongodb", "mongo"},
    "redis": {"redis"},
    "elasticsearch": {"elasticsearch", "elastic search", "opensearch"},
    "dynamodb": {"dynamodb", "dynamo db"},
    "sqlite": {"sqlite", "sqlite3"},
    "graphql": {"graphql", "graph ql"},
    "rest api": {"rest api", "restful", "rest apis", "rest"},
    "microservices": {"microservices", "micro-services", "microservice"},
    "kafka": {"kafka", "apache kafka"},
    "rabbitmq": {"rabbitmq", "rabbit mq"},
    # Data / AI
    "machine learning": {"machine learning", "ml"},
    "deep learning": {"deep learning", "dl"},
    "tensorflow": {"tensorflow"},
    "pytorch": {"pytorch", "torch"},
    "nlp": {"natural language processing", "nlp"},
    "computer vision": {"computer vision"},
    "data science": {"data science"},
    "data engineering": {"data engineering"},
    "pandas": {"pandas"},
    "numpy": {"numpy"},
    "scikit-learn": {"scikit-learn", "sklearn", "scikit learn"},
    "spark": {"spark", "pyspark", "apache spark"},
    "hadoop": {"hadoop"},
    "airflow": {"airflow", "apache airflow"},
    "etl": {"etl", "elt"},
    "llm": {"llm", "large language model", "llms", "genai", "generative ai"},
    # Web
    "figma": {"figma"},
    "ui/ux": {"ui/ux", "ux", "ui design", "user experience", "user interface"},
    "photoshop": {"photoshop"},
    "illustrator": {"illustrator"},
    # General tech
    "git": {"git", "github", "gitlab", "bitbucket"},
    "linux": {"linux", "unix"},
    "bash": {"bash", "shell", " zsh "},
    "networking": {"networking", "tcp/ip", " http ", " https "},
    "security": {"security", "cybersecurity", "infosec", "oauth", "jwt"},
    "testing": {"testing", "unit testing", "pytest", "jest", "junit", "qa", "test automation"},
    "agile": {"agile", "scrum", "kanban", "jira"},
    "leadership": {"leadership", "team lead", "mentoring"},
    "communication": {"communication"},
    "project management": {"project management", "pmp"},
    "product management": {"product management", "product manager"},
    "sales": {"sales", "b2b sales", "b2c sales"},
    "marketing": {"marketing", "digital marketing", "seo", "sem"},
    "customer service": {"customer service", "customer support"},
    "operations": {"operations", " ops "},
    "finance": {"finance", "financial analysis", "accounting"},
    "strategy": {"strategy", "strategic planning"},
    "analysis": {"analysis", "data analysis", "analytical"},
    "teamwork": {"teamwork"},
    "time management": {"time management"},
}

# Build (alias -> canonical) reverse map once at import time.
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias.lower()] = canonical


# Common false-positive tokens to strip from any text before skill extraction.
_STOPWORDS = {
    "a", "an", "and", "or", "the", "to", "of", "in", "on", "for", "with", "at",
    "is", "are", "be", "as", "by", "this", "that", "it", "from", "i", "we",
    "you", "they", "he", "she", "but", "not", "have", "has", "had", "will",
    "would", "can", "could", "should", "do", "does", "did", "if", "else",
    "their", "our", "my", "your", "his", "her", "its", "been", "being", "am",
}


# =============================================================================
# Helpers
# =============================================================================
def _tokenize_for_word_boundary(text: str) -> str:
    """Lowercase + pad with spaces so word-boundary regexes work cleanly."""
    return f" {re.sub(r'[^a-z0-9+.#/&-]', ' ', text.lower())} "


def extract_skills_from_text(text) -> Set[str]:
    """Extract skills from text using word-boundary regex on the alias map.

    Empty / non-string input -> empty set. Returns the *set of canonical
    skill names* found (so "Postgres" and "PostgreSQL" collapse to
    "postgresql").
    """
    if not text or not isinstance(text, str):
        return set()
    padded = _tokenize_for_word_boundary(text)
    found: Set[str] = set()
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        # Word boundary at the start & end. \b in python regex treats
        # non-word characters as boundaries, which is what we want.
        pattern = r"(?<![a-z0-9+#])" + re.escape(alias) + r"(?![a-z0-9+#])"
        if re.search(pattern, padded):
            found.add(canonical)
    return found


def _extract_title_tokens(text: str) -> Set[str]:
    """Extract meaningful tokens from a job title or resume headline."""
    if not text:
        return set()
    tokens = re.findall(r"[a-z][a-z+#./-]{1,}", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _normalize_skill_list(skills_field, description: str = "") -> List[str]:
    """Extract skills from a job's `requirements` field (which may be a list
    or a comma-separated string) plus its description.
    """
    parts: List[str] = []
    if isinstance(skills_field, list):
        parts.extend(str(s) for s in skills_field)
    elif isinstance(skills_field, str):
        parts.append(skills_field)
    if description:
        parts.append(description)
    combined = " ".join(parts)
    return sorted(extract_skills_from_text(combined))


def _extract_years_experience(text: str) -> Optional[int]:
    """Best-effort parse of years of experience from a resume."""
    if not text:
        return None
    matches = re.findall(
        r"(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)?",
        text.lower(),
    )
    if not matches:
        return None
    try:
        return max(int(m) for m in matches)
    except ValueError:
        return None


# Backwards-compat: keep the old public name working.
def calculate_match_score(
    resume_skills: Set[str], job_skills: Set[str]
) -> Tuple[int, List[str], List[str]]:
    """Legacy entry point: |matched| / |job_skills| * 100.

    Kept for compatibility with anything that imported the old name. Prefer
    `calculate_match` for the new weighted score.
    """
    if not job_skills:
        return 0, [], []
    matched = resume_skills.intersection(job_skills)
    missing = job_skills - resume_skills
    score = int((len(matched) / len(job_skills)) * 100)
    score = min(100, max(0, score))
    return score, list(matched), list(missing)


# =============================================================================
# Scoring
# =============================================================================
def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _title_similarity(resume_text: str, job_title: str) -> float:
    """0..1 score for how close the resume's headline is to the job title."""
    if not resume_text or not job_title:
        return 0.0
    # Use the first non-empty line of the resume as the "headline"
    headline = ""
    for line in resume_text.splitlines():
        line = line.strip()
        if line:
            headline = line
            break
    a = _extract_title_tokens(headline)
    b = _extract_title_tokens(job_title)
    return _jaccard(a, b)


def _location_fit(job: Dict, career_prefs: Optional[Dict]) -> Tuple[float, bool]:
    """Return (score 0..1, hard-fail?). Considers remote flag and location list."""
    if not career_prefs:
        return 0.5, False
    remote_only = bool(career_prefs.get("remote_only"))
    preferred_locations = career_prefs.get("preferred_locations") or []
    is_remote = bool(job.get("is_remote"))
    job_location = (job.get("location") or "").lower()

    if remote_only and not is_remote:
        return 0.0, True

    if not preferred_locations:
        return (1.0 if is_remote else 0.5), False

    if any(loc and loc.lower() in job_location for loc in preferred_locations):
        return 1.0, False
    if is_remote:
        return 0.7, False
    return 0.2, False


def _salary_fit(job: Dict, career_prefs: Optional[Dict]) -> float:
    """0..1. Returns 0.5 (neutral) if no salary info or no preference."""
    if not career_prefs:
        return 0.5
    min_salary = career_prefs.get("min_salary")
    if not min_salary:
        return 0.5
    salary_range = job.get("salary_range") or ""
    nums = re.findall(r"\d[\d,]*", salary_range)
    if not nums:
        return 0.5
    try:
        job_min = int(nums[0].replace(",", ""))
    except ValueError:
        return 0.5
    if job_min >= min_salary:
        return 1.0
    return max(0.0, job_min / max(min_salary, 1))


def _build_match_reason(
    matched_skills: List[str],
    missing_skills: List[str],
    title_score: float,
    career_prefs: Optional[Dict],
    job: Dict,
) -> str:
    """Human-readable 1-sentence reason explaining why this job was matched."""
    parts: List[str] = []
    if matched_skills:
        top = matched_skills[:3]
        parts.append(f"matched skills: {', '.join(top)}")
    if missing_skills:
        parts.append(f"missing: {', '.join(missing_skills[:3])}")
    if title_score >= 50:
        parts.append("title overlaps your resume headline")
    if career_prefs:
        preferred_titles = career_prefs.get("preferred_titles") or career_prefs.get("preferred_job_titles") or []
        if preferred_titles and any(t and t.lower() in (job.get("title") or "").lower() for t in preferred_titles):
            parts.append("matches your preferred title")
    if not parts:
        return "Low overall fit."
    return " | ".join(parts)


def calculate_match(
    resume_content: str,
    job: Dict,
    career_prefs: Optional[Dict] = None,
) -> JobMatchResponse:
    """Score a single job against a resume + career preferences.

    Final score is a weighted blend:
        - 60%  skill overlap (Jaccard on canonical skill sets)
        - 25%  title similarity
        - 10%  location/remote fit
        -  5%  salary fit
    Plus small boosts for matching `preferred_titles` (+10) and
    `preferred_skills` (+5..+10), and a small boost for keyword hits (+5).
    """
    resume_skills = extract_skills_from_text(resume_content)
    job_skills = set(_normalize_skill_list(
        job.get("requirements"), job.get("description", "")
    ))

    matched_skills = sorted(resume_skills & job_skills)
    missing_skills = sorted(job_skills - resume_skills)

    skill_score = _jaccard(resume_skills, job_skills) * 100
    title_score = _title_similarity(resume_content, job.get("title", "")) * 100
    loc_score, _loc_hard_fail = _location_fit(job, career_prefs)
    sal_score = _salary_fit(job, career_prefs)

    score = (
        0.60 * skill_score
        + 0.25 * title_score
        + 0.10 * (loc_score * 100)
        + 0.05 * (sal_score * 100)
    )

    if career_prefs:
        preferred_titles = (
            career_prefs.get("preferred_titles")
            or career_prefs.get("preferred_job_titles")
            or []
        )
        if preferred_titles:
            jt = (job.get("title") or "").lower()
            if any(t and t.lower() in jt for t in preferred_titles):
                score += 10.0

        preferred_skills = career_prefs.get("preferred_skills") or []
        if preferred_skills:
            canon_preferred = {s for s in (p.lower().strip() for p in preferred_skills) if s}
            if canon_preferred & job_skills:
                score += min(10.0, 5.0 + 5.0 * len(canon_preferred & job_skills))

        keywords = career_prefs.get("keywords") or []
        if keywords:
            haystack = " ".join(
                str(job.get(k, "")) for k in
                ("title", "description", "requirements", "company", "location")
            ).lower()
            hits = sum(1 for k in keywords if k and k.lower() in haystack)
            if hits:
                score += min(5.0, 2.0 * hits)

    score = max(0.0, min(100.0, score))
    final_score = int(round(score))

    match_reason = _build_match_reason(
        matched_skills, missing_skills, title_score, career_prefs, job
    )

    return JobMatchResponse(
        id=job["id"],
        title=job["title"],
        company=job["company"],
        location=job["location"],
        description=job.get("description"),
        requirements=job.get("requirements"),
        salary_range=job.get("salary_range"),
        job_type=job.get("job_type"),
        source=job["source"],
        source_url=job.get("source_url"),
        posted_at=job.get("posted_at"),
        is_remote=job.get("is_remote", False),
        created_at=job.get("posted_at") or datetime.utcnow(),
        match_score=final_score,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        match_reason=match_reason,
    )


# =============================================================================
# Scrapers
# =============================================================================
class JobScraper:
    """Scraper for real job listings from external APIs."""

    def __init__(self):
        self.session: Optional[httpx.AsyncClient] = None
        self._cached_jobs: List[Dict] = []
        self._last_fetch: Optional[datetime] = None
        self.cache_ttl_seconds = 300

    async def _get_session(self) -> httpx.AsyncClient:
        if self.session is None or self.session.is_closed:
            self.session = httpx.AsyncClient(
                headers={"User-Agent": "GeniusJobPlatform/1.0"},
                follow_redirects=True,
            )
        return self.session

    async def close(self):
        if self.session and not self.session.is_closed:
            await self.session.aclose()

    # ----- OpenWebNinja JSearch (primary, no RapidAPI key needed) -----
    async def fetch_jsearch_openwebninja_jobs(
        self, query: str = "developer", page: int = 1
    ) -> List[Dict]:
        """Fetch jobs from OpenWebNinja's JSearch endpoint.

        Free tier requires only the X-API-Key header (no RapidAPI).
        Set the env var JSEARCH_OPENWEBNINJA_API_KEY to enable. The key is
        read at call time so you can rotate it without a redeploy.
        """
        api_key = os.getenv("JSEARCH_OPENWEBNINJA_API_KEY")
        if not api_key:
            logger.info(
                "JSEARCH_OPENWEBNINJA_API_KEY not set; skipping OpenWebNinja JSearch"
            )
            return []
        try:
            session = await self._get_session()
            response = await session.get(
                "https://api.openwebninja.com/jsearch/search-v2",
                params={"query": query, "page": str(page)},
                headers={"X-API-Key": api_key},
                timeout=httpx.Timeout(30.0),
            )
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("data") or data.get("jobs") or []
                logger.info(f"OpenWebNinja JSearch jobs count: {len(jobs)}")
                return [self._transform_jsearch_openwebninja(j) for j in jobs]
            logger.warning(
                f"OpenWebNinja JSearch returned {response.status_code}: {response.text[:200]}"
            )
            return []
        except Exception as e:
            logger.error(f"Error fetching OpenWebNinja JSearch jobs: {e}")
            return []

    def _transform_jsearch_openwebninja(self, job: Dict) -> Dict:
        employer = job.get("employer") or {}
        salary = job.get("salary") or {}
        salary_range = ""
        if salary.get("min") and salary.get("max"):
            salary_range = f"${salary['min']} - ${salary['max']}"
        elif salary.get("min"):
            salary_range = f"${salary['min']}+"
        posted = job.get("job_posted_at_datetime_utc") or job.get("job_posted_at")
        try:
            posted_at = (
                datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else datetime.utcnow()
            )
        except Exception:
            posted_at = datetime.utcnow()
        return {
            "id": f"own_{job.get('job_id', '')}",
            "title": job.get("job_title", ""),
            "company": employer.get("company_name", ""),
            "location": job.get("job_city")
            or job.get("job_country")
            or ("Remote" if job.get("job_is_remote") else ""),
            "description": job.get("job_description", ""),
            "requirements": ", ".join(job.get("job_required_skills") or []),
            "salary_range": salary_range,
            "job_type": job.get("job_employment_type", "Full-time"),
            "source": "JSearch (OpenWebNinja)",
            "source_url": job.get("job_apply_link", ""),
            "posted_at": posted_at,
            "is_remote": bool(job.get("job_is_remote")),
        }

    # ----- RapidAPI JSearch (legacy fallback) -----
    async def fetch_jsearch_jobs(
        self, query: str = "", page: int = 1, num_pages: int = 1
    ) -> List[Dict]:
        api_key = os.getenv("JSEARCH_API_KEY") or os.getenv("RAPIDAPI_KEY")
        if not api_key:
            logger.info("RAPIDAPI_KEY not set; skipping RapidAPI JSearch")
            return []
        try:
            session = await self._get_session()
            all_jobs: List[Dict] = []
            for current_page in range(page, page + num_pages):
                response = await session.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers={
                        "X-RapidAPI-Key": api_key,
                        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                    },
                    params={
                        "query": query or "developer",
                        "page": str(current_page),
                        "num_pages": "1",
                    },
                    timeout=httpx.Timeout(30.0),
                )
                if response.status_code == 200:
                    data = response.json()
                    jobs = data.get("data", [])
                    all_jobs.extend([self._transform_jsearch_rapid(j) for j in jobs])
                else:
                    logger.warning(
                        f"RapidAPI JSearch returned {response.status_code} for page {current_page}"
                    )
                    break
            return all_jobs
        except Exception as e:
            logger.error(f"Error fetching RapidAPI JSearch jobs: {e}")
            return []

    def _transform_jsearch_rapid(self, job: Dict) -> Dict:
        employer = job.get("employer") or {}
        salary = job.get("salary") or {}
        salary_range = ""
        if salary.get("min") and salary.get("max"):
            salary_range = f"${salary['min']} - ${salary['max']}"
        elif salary.get("min"):
            salary_range = f"${salary['min']}+"
        posted = job.get("job_posted_at_datetime_utc")
        try:
            posted_at = (
                datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else datetime.utcnow()
            )
        except Exception:
            posted_at = datetime.utcnow()
        return {
            "id": f"jsearch_{job.get('job_id', '')}",
            "title": job.get("job_title", ""),
            "company": employer.get("company_name", ""),
            "location": job.get("job_city", "") or "Remote",
            "description": job.get("job_description", ""),
            "requirements": ", ".join(job.get("job_required_skills") or []),
            "salary_range": salary_range,
            "job_type": job.get("job_employment_type", "Full-time"),
            "source": "JSearch (RapidAPI)",
            "source_url": job.get("job_apply_link", ""),
            "posted_at": posted_at,
            "is_remote": bool(job.get("job_is_remote")),
        }

    # ----- Remotive -----
    async def fetch_remotive_jobs(self, category: str = "remote") -> List[Dict]:
        try:
            session = await self._get_session()
            url = f"https://remotive.com/api/{category}-jobs?limit=50"
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                logger.info(f"Remotive jobs count: {len(jobs)}")
                return [self._transform_remotive_job(j) for j in jobs]
            logger.warning(f"Remotive API returned {response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching Remotive jobs: {e}")
            return []

    def _transform_remotive_job(self, job: Dict) -> Dict:
        posted = job.get("publication_date")
        try:
            posted_at = (
                datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else datetime.utcnow()
            )
        except Exception:
            posted_at = datetime.utcnow()
        return {
            "id": f"remotive_{job.get('id', '')}",
            "title": job.get("title", ""),
            "company": job.get("company_name", ""),
            "location": job.get("candidate_required_location", "Remote"),
            "description": job.get("description", ""),
            "requirements": self._html_to_text(job.get("description", "")),
            "salary_range": job.get("salary", "") or "",
            "job_type": job.get("job_type", "Full-time"),
            "source": "Remotive",
            "source_url": job.get("url", ""),
            "posted_at": posted_at,
            "is_remote": True,
        }

    # ----- The Muse -----
    async def fetch_themuse_jobs(self, page: int = 0) -> List[Dict]:
        try:
            session = await self._get_session()
            url = f"https://www.themuse.com/api/public/jobs?page={page}&descending=true"
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("results", [])
                logger.info(f"The Muse jobs count: {len(jobs)}")
                return [self._transform_themuse_job(j) for j in jobs]
            logger.warning(f"The Muse API returned {response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching The Muse jobs: {e}")
            return []

    def _transform_themuse_job(self, job: Dict) -> Dict:
        posted = job.get("publication_date")
        try:
            posted_at = (
                datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else datetime.utcnow()
            )
        except Exception:
            posted_at = datetime.utcnow()
        return {
            "id": f"themuse_{job.get('id', '')}",
            "title": job.get("name", ""),
            "company": (job.get("company") or {}).get("name", ""),
            "location": (
                job.get("locations", [{}])[0].get("name", "Remote")
                if job.get("locations")
                else "Remote"
            ),
            "description": job.get("contents", ""),
            "requirements": "",
            "salary_range": "",
            "job_type": "Full-time",
            "source": "The Muse",
            "source_url": (job.get("refs") or {}).get("landing_page", ""),
            "posted_at": posted_at,
            "is_remote": "remote" in (job.get("name") or "").lower()
            or any(
                "remote" in (loc.get("name") or "").lower()
                for loc in (job.get("locations") or [])
            ),
        }

    # ----- Optional providers (no-op without keys) -----
    async def fetch_adzuna_jobs(self, query: str = "", location: str = "", page: int = 1) -> List[Dict]:
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            return []
        try:
            session = await self._get_session()
            params = {"app_id": app_id, "app_key": app_key, "results_per_page": 20}
            if query:
                params["what"] = query
            if location:
                params["where"] = location
            response = await session.get(
                f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                params=params,
                timeout=httpx.Timeout(30.0),
            )
            if response.status_code == 200:
                data = response.json()
                return [self._transform_adzuna_job(j) for j in data.get("results", [])]
            return []
        except Exception as e:
            logger.error(f"Adzuna error: {e}")
            return []

    def _transform_adzuna_job(self, job: Dict) -> Dict:
        created = job.get("created")
        try:
            posted_at = (
                datetime.fromisoformat(created.replace("Z", "+00:00")) if created else datetime.utcnow()
            )
        except Exception:
            posted_at = datetime.utcnow()
        return {
            "id": f"adzuna_{job.get('id', '')}",
            "title": job.get("title", ""),
            "company": (job.get("company") or {}).get("display_name", ""),
            "location": (job.get("location") or {}).get("display_name", ""),
            "description": job.get("description", ""),
            "requirements": "",
            "salary_range": str(job.get("salary_min") or ""),
            "job_type": job.get("contract_type", "Full-time"),
            "source": "Adzuna",
            "source_url": job.get("redirect_url", ""),
            "posted_at": posted_at,
            "is_remote": False,
        }

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def scrape_all_jobs(self, force_refresh: bool = False) -> List[Dict]:
        """Scrape jobs from all sources and combine. Single network pass."""
        if (
            not force_refresh
            and self._cached_jobs
            and self._last_fetch
            and (datetime.utcnow() - self._last_fetch).total_seconds() < self.cache_ttl_seconds
        ):
            return self._cached_jobs

        logger.info("Scraping jobs from external sources...")
        tasks = [
            self.fetch_jsearch_openwebninja_jobs("developer", 1),
            self.fetch_jsearch_openwebninja_jobs("engineer", 1),
            self.fetch_remotive_jobs("remote"),
            self.fetch_themuse_jobs(0),
            self.fetch_themuse_jobs(1),
            self.fetch_jsearch_jobs("developer", 1, 1),  # legacy fallback
            self.fetch_adzuna_jobs("", "", 1),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_jobs: List[Dict] = []
        for result in results:
            if isinstance(result, list):
                all_jobs.extend(result)

        self._cached_jobs = all_jobs
        self._last_fetch = datetime.utcnow()
        logger.info(f"Scraped {len(all_jobs)} jobs total")
        return all_jobs


# =============================================================================
# Service
# =============================================================================
class JobService:
    """Service for job management with the new weighted match scorer."""

    # Minimum score a job must hit to be shown in recommendations.
    MIN_RECOMMENDATION_SCORE = 20

    def __init__(self):
        self.scraper = JobScraper()
        self._sample_jobs: List[Dict] = self._get_sample_jobs()

    # ---------------- Sample jobs (fallback when no live data) ----------------
    def _get_sample_jobs(self) -> List[Dict]:
        return [
            {
                "id": "sample_backend_python",
                "title": "Senior Python Backend Engineer",
                "company": "Acme Cloud",
                "location": "Remote",
                "description": (
                    "Build scalable APIs with Python, FastAPI, and PostgreSQL. "
                    "Deploy to AWS using Docker and Kubernetes. CI/CD, REST APIs, "
                    "microservices experience required."
                ),
                "requirements": "python, fastapi, postgresql, docker, kubernetes, aws, rest api, microservices",
                "salary_range": "$130,000 - $180,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
            {
                "id": "sample_frontend_react",
                "title": "Senior Frontend Engineer (React)",
                "company": "Pixel Studio",
                "location": "Remote",
                "description": "Build the next generation of our React/TypeScript dashboard. Strong CSS skills required.",
                "requirements": "react, typescript, javascript, css, html, figma",
                "salary_range": "$120,000 - $170,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
            {
                "id": "sample_data_scientist",
                "title": "Data Scientist",
                "company": "Insight Labs",
                "location": "New York, NY",
                "description": "Build ML models with Python, scikit-learn, and TensorFlow. SQL required.",
                "requirements": "python, machine learning, scikit-learn, tensorflow, sql, pandas",
                "salary_range": "$140,000 - $200,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": False,
            },
            {
                "id": "sample_devops",
                "title": "DevOps / SRE",
                "company": "CloudOps Inc",
                "location": "Remote",
                "description": "Own our AWS infrastructure, Terraform, Kubernetes, and CI/CD pipelines.",
                "requirements": "aws, terraform, kubernetes, docker, ci/cd, jenkins, linux",
                "salary_range": "$130,000 - $190,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
            {
                "id": "sample_ios",
                "title": "iOS Developer",
                "company": "MobileFirst",
                "location": "San Francisco, CA",
                "description": "Build iOS apps in Swift / SwiftUI.",
                "requirements": "swift, ios, swiftui, xcode",
                "salary_range": "$130,000 - $190,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": False,
            },
            {
                "id": "sample_fullstack",
                "title": "Full Stack Developer",
                "company": "Growth Co",
                "location": "Remote",
                "description": "Node.js + React full-stack work on a small team.",
                "requirements": "node.js, react, typescript, postgresql, docker",
                "salary_range": "$110,000 - $160,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
            {
                "id": "sample_ml_engineer",
                "title": "ML Engineer",
                "company": "AI Works",
                "location": "Remote",
                "description": "Train and deploy LLMs. Python, PyTorch, and MLOps experience required.",
                "requirements": "python, pytorch, machine learning, llm, docker, aws",
                "salary_range": "$150,000 - $220,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
            {
                "id": "sample_android",
                "title": "Android Engineer",
                "company": "MobileFirst",
                "location": "Remote",
                "description": "Build Android apps with Kotlin and Jetpack Compose.",
                "requirements": "kotlin, android, jetpack compose",
                "salary_range": "$120,000 - $170,000",
                "job_type": "Full-time",
                "source": "Sample",
                "source_url": "",
                "posted_at": datetime.utcnow(),
                "is_remote": True,
            },
        ]

    # ---------------- Lifecycle ----------------
    async def initialize(self):
        try:
            await self.scraper.scrape_all_jobs(force_refresh=True)
        except Exception as e:
            logger.warning(f"Initial job scrape failed, using samples: {e}")

    # ---------------- Public API ----------------
    async def _collect_all_jobs(self, use_live_data: bool = True) -> List[Dict]:
        """Single network pass; dedupes by ID with live > sample priority."""
        if use_live_data:
            try:
                live_jobs = await self.scraper.scrape_all_jobs()
            except Exception as e:
                logger.warning(f"scrape_all_jobs failed, falling back to samples: {e}")
                live_jobs = []
            combined = live_jobs + self._sample_jobs
        else:
            combined = list(self._sample_jobs)

        seen: Set[str] = set()
        unique: List[Dict] = []
        for job in combined:
            jid = job.get("id")
            if jid and jid not in seen:
                seen.add(jid)
                unique.append(job)
        return unique

    async def search_jobs(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        remote: Optional[bool] = None,
        job_type: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
        use_live_data: bool = True,
    ) -> List[Dict]:
        jobs = await self._collect_all_jobs(use_live_data=use_live_data)

        if query:
            q = query.lower()
            jobs = [
                j for j in jobs
                if q in (j.get("title") or "").lower()
                or q in (j.get("company") or "").lower()
                or q in (j.get("description") or "").lower()
                or q in (j.get("requirements") or "").lower()
            ]
        if location:
            loc = location.lower()
            jobs = [j for j in jobs if loc in (j.get("location") or "").lower()]
        if remote is not None:
            jobs = [j for j in jobs if bool(j.get("is_remote")) == remote]
        if job_type:
            jobs = [j for j in jobs if j.get("job_type") == job_type]

        start = (page - 1) * limit
        return jobs[start:start + limit]

    async def match_with_resume(
        self,
        job_id: str,
        resume_content: str,
        career_prefs: Optional[Dict] = None,
    ) -> Optional[JobMatchResponse]:
        all_jobs = await self._collect_all_jobs(use_live_data=True)
        job = next((j for j in all_jobs if j.get("id") == job_id), None)
        if not job:
            return None
        return calculate_match(resume_content, job, career_prefs)

    async def get_recommendations(
        self,
        resume_content: str,
        career_preferences: Optional[Dict] = None,
        limit: int = 6,
    ) -> List[JobMatchResponse]:
        """Score every available job in a SINGLE pass and return the top N.

        Improvements over the previous implementation:
          - Single network scrape (no N+1).
          - Uses the weighted `calculate_match` (skills + title + location + salary).
          - Respects ALL `career_preferences` (titles, locations, skills, keywords, remote_only, min_salary).
          - Falls back to "soft match" if the strict title filter would return 0.
          - Drops jobs below `MIN_RECOMMENDATION_SCORE` so the user never sees noise.
          - Returns a `match_reason` per result.
        """
        all_jobs = await self._collect_all_jobs(use_live_data=True)
        prefs = career_preferences or {}

        # 1) Apply *soft* title/location/remote/type filters. They are boosts,
        #    not hard filters, so a too-strict preference still yields results.
        candidate_jobs = list(all_jobs)

        # 2) Hard filter: remote_only (no point scoring a non-remote job for
        #    someone who explicitly wants remote).
        if prefs.get("remote_only"):
            candidate_jobs = [j for j in candidate_jobs if j.get("is_remote")]

        # 3) Hard filter: job_types
        allowed_types = prefs.get("job_types") or []
        if allowed_types:
            allowed_lc = {t.lower() for t in allowed_types if t}
            candidate_jobs = [
                j for j in candidate_jobs
                if (j.get("job_type") or "").lower() in allowed_lc
            ]

        # If the user gave a title preference, try a strict title filter first.
        # If that empties the list, fall back to scoring everything (with a
        # title-boost in the score so the preference still influences order).
        preferred_titles = (
            prefs.get("preferred_titles") or prefs.get("preferred_job_titles") or []
        )
        strict_titled = []
        if preferred_titles:
            strict_titled = [
                j for j in candidate_jobs
                if any(
                    t and t.lower() in (j.get("title") or "").lower()
                    for t in preferred_titles
                )
            ]
            if strict_titled:
                candidate_jobs = strict_titled

        if not candidate_jobs:
            # No jobs at all — nothing to score.
            return []

        # 4) Score each candidate in-memory. No extra network calls.
        scored: List[JobMatchResponse] = []
        for job in candidate_jobs:
            try:
                m = calculate_match(resume_content, job, prefs)
            except Exception as e:
                logger.warning(f"calculate_match failed for {job.get('id')}: {e}")
                continue
            if (m.match_score or 0) >= self.MIN_RECOMMENDATION_SCORE:
                scored.append(m)

        # 5) Sort by score desc, then by id for stability.
        scored.sort(key=lambda x: (-(x.match_score or 0), x.id))

        # 6) Light diversification: if the top 3 are all the same source/role,
        #    sprinkle in the next best from a different source/role. Keeps the
        #    recommendations from feeling like the same job repeated.
        diversified: List[JobMatchResponse] = []
        seen_signatures: Set[str] = set()
        reserve: List[JobMatchResponse] = []
        for m in scored:
            sig = f"{(m.title or '').lower().split('(')[0].strip()}|{(m.company or '').lower()}"
            if sig in seen_signatures:
                reserve.append(m)
                continue
            diversified.append(m)
            seen_signatures.add(sig)
            if len(diversified) >= limit:
                break
        for m in reserve:
            if len(diversified) >= limit:
                break
            diversified.append(m)
        return diversified[:limit]

    async def get_live_job_count(self) -> int:
        try:
            jobs = await self.scraper.scrape_all_jobs()
        except Exception:
            jobs = []
        return len(jobs)


job_service = JobService()
