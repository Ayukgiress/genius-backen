import asyncio
import json
import os
import re
import httpx
import logging
from datetime import datetime
from typing import List, Optional, Dict, Set
from app.schemas.job import JobCreate, JobMatchResponse
from app.models.job import Job

logger = logging.getLogger(__name__)

COMMON_SKILLS = {
    # Tech - Languages & Frameworks
    "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#", "php", "ruby", "swift", "kotlin",
    "react", "vue", "angular", "next.js", "node.js", "express", "django", "flask", "laravel", "spring",
    # Cloud & DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "jenkins", "github actions", "ci/cd",
    "sql", "postgresql", "mysql", "mongodb", "redis", "graphql", "rest api", "microservices",
    # Data & AI
    "machine learning", "tensorflow", "pytorch", "nlp", "data science", "pandas", "numpy", "scikit-learn",
    "spark", "hadoop", "kafka", "airflow", "etl", "data engineering",
    # Soft Skills & Business
    "project management", "agile", "scrum", "leadership", "communication", "problem solving",
    "product management", "sales", "marketing", "customer service", "operations", "finance",
    "strategy", "analysis", "teamwork", "organization", "time management", "creativity",
    # Design
    "ui/ux", "figma", "adobe xd", "photoshop", "illustrator", "design system",
    # General Tech
    "git", "linux", "unix", "bash", "shell", "networking", "security", "testing", "qa",
}


def extract_skills_from_text(text: str) -> Set[str]:
    """Extract skills from text (job description or resume)."""
    if not text:
        return set()
    text_lower = text.lower()
    found_skills = set()
    for skill in COMMON_SKILLS:
        if skill in text_lower:
            found_skills.add(skill)
    return found_skills


def calculate_match_score(resume_skills: Set[str], job_skills: Set[str]) -> tuple[int, List[str], List[str]]:
    """Calculate match score between resume and job requirements."""
    if not job_skills:
        return 0, [], []
    
    matched = resume_skills.intersection(job_skills)
    missing = job_skills - resume_skills
    
    score = int((len(matched) / len(job_skills)) * 100)
    score = min(100, max(0, score))
    
    return score, list(matched), list(missing)


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
                follow_redirects=True
            )
        return self.session
    
    async def close(self):
        if self.session and not self.session.is_closed:
            await self.session.aclose()
    
    async def fetch_remotive_jobs(self, category: str = "remote") -> List[Dict]:
        """Fetch jobs from Remotive API (free, no auth required)."""
        try:
            session = await self._get_session()
            url = f"https://remotive.com/api/{category}-jobs?limit=50"
            logger.info(f"Fetching Remotive jobs from: {url}")
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            logger.info(f"Remotive response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                logger.info(f"Remotive jobs count: {len(jobs)}")
                return [self._transform_remotive_job(job) for job in jobs]
            else:
                logger.warning(f"Remotive API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching Remotive jobs: {e}")
            return []
    
    def _transform_remotive_job(self, job: Dict) -> Dict:
        """Transform Remotive job format to our schema."""
        return {
            "id": f"remotive_{job.get('id', '')}",
            "title": job.get("title", ""),
            "company": job.get("company_name", ""),
            "location": job.get("candidate_required_location", "Remote"),
            "description": job.get("description", ""),
            "requirements": self._extract_requirements_from_html(job.get("description", "")),
            "salary_range": job.get("salary", ""),
            "job_type": job.get("job_type", "Full-time"),
            "source": "Remotive",
            "source_url": job.get("url", ""),
            "posted_at": datetime.fromisoformat(job.get("publication_date", datetime.now().isoformat()).replace("Z", "+00:00")) if job.get("publication_date") else datetime.now(),
            "is_remote": True,
        }
    
    async def fetch_themuse_jobs(self, page: int = 0) -> List[Dict]:
        """Fetch jobs from The Muse API (free, no auth required)."""
        try:
            session = await self._get_session()
            url = f"https://www.themuse.com/api/public/jobs?page={page}&descending=true"
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("results", [])
                logger.info(f"The Muse jobs count: {len(jobs)}")
                return [self._transform_themuse_job(job) for job in jobs]
            else:
                logger.warning(f"The Muse API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching The Muse jobs: {e}")
            return []

    def _transform_themuse_job(self, job: Dict) -> Dict:
        """Transform The Muse job format to our schema."""
        return {
            "id": f"themuse_{job.get('id', '')}",
            "title": job.get("name", ""),
            "company": job.get("company", {}).get("name", ""),
            "location": job.get("locations", [{}])[0].get("name", "Remote") if job.get("locations") else "Remote",
            "description": job.get("contents", ""),
            "requirements": "",  # The Muse doesn't provide structured requirements
            "salary_range": "",
            "job_type": "Full-time",
            "source": "The Muse",
            "source_url": job.get("refs", {}).get("landing_page", ""),
            "posted_at": datetime.fromisoformat(job.get("publication_date", datetime.now().isoformat()).replace("Z", "+00:00")) if job.get("publication_date") else datetime.now(),
            "is_remote": "remote" in job.get("name", "").lower() or any("remote" in loc.get("name", "").lower() for loc in job.get("locations", [])),
        }

    async def fetch_jsearch_jobs(self, query: str = "", page: int = 1, num_pages: int = 1) -> List[Dict]:
        """Fetch jobs from JSearch API (free tier: 200 requests/month, requires RAPIDAPI_KEY env var)."""
        try:
            # JSearch requires an API key from RapidAPI
            api_key = os.getenv("JSEARCH_API_KEY") or os.getenv("RAPIDAPI_KEY")
            if not api_key:
                logger.info("JSearch API key not available (set RAPIDAPI_KEY env var for 200 free requests/month), skipping")
                return []

            session = await self._get_session()
            headers = {
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
            }

            all_jobs = []
            for current_page in range(page, page + num_pages):
                params = {
                    "query": query or "developer",
                    "page": str(current_page),
                    "num_pages": "1"
                }

                response = await session.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params=params,
                    timeout=httpx.Timeout(30.0)
                )

                if response.status_code == 200:
                    data = response.json()
                    jobs = data.get("data", [])
                    all_jobs.extend([self._transform_jsearch_job(job) for job in jobs])
                else:
                    logger.warning(f"JSearch API returned status {response.status_code} for page {current_page}")
                    break

            logger.info(f"JSearch jobs count: {len(all_jobs)}")
            return all_jobs
        except Exception as e:
            logger.error(f"Error fetching JSearch jobs: {e}")
            return []

    async def fetch_jobdatalake_jobs(self, page: int = 1, per_page: int = 20, query: str = "") -> List[Dict]:
        """Fetch jobs from JobDataLake API (free tier: 1000 credits, requires JOBDATALAKE_API_KEY env var)."""
        try:
            # Note: This requires an API key. For now, we'll skip if no key is available
            api_key = os.getenv("JOBDATALAKE_API_KEY")
            if not api_key:
                logger.info("JobDataLake API key not available (free tier available at jobdatalake.com), skipping")
                return []

            session = await self._get_session()
            headers = {"X-API-Key": api_key}
            params = {"page": page, "per_page": per_page}
            if query:
                params["q"] = query

            response = await session.get("https://api.jobdatalake.com/v1/jobs", headers=headers, params=params, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("data", [])
                logger.info(f"JobDataLake jobs count: {len(jobs)}")
                return [self._transform_jobdatalake_job(job) for job in jobs]
            else:
                logger.warning(f"JobDataLake API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching JobDataLake jobs: {e}")
            return []

    async def fetch_adzuna_jobs(self, query: str = "", location: str = "", page: int = 1) -> List[Dict]:
        """Fetch jobs from Adzuna API (free tier available, requires ADZUNA_APP_ID and ADZUNA_APP_KEY env vars)."""
        try:
            # Note: This requires app_id and app_key
            app_id = os.getenv("ADZUNA_APP_ID")
            app_key = os.getenv("ADZUNA_APP_KEY")
            if not app_id or not app_key:
                logger.info("Adzuna API credentials not available (free signup at developer.adzuna.com), skipping")
                return []

            session = await self._get_session()
            params = {"app_id": app_id, "app_key": app_key, "results_per_page": 20}

            if query:
                params["what"] = query
            if location:
                params["where"] = location

            url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}"
            response = await session.get(url, params=params, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("results", [])
                logger.info(f"Adzuna jobs count: {len(jobs)}")
                return [self._transform_adzuna_job(job) for job in jobs]
            else:
                logger.warning(f"Adzuna API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching Adzuna jobs: {e}")
            return []

    async def fetch_indeed_jobs(self, query: str = "", location: str = "", start: int = 0) -> List[Dict]:
        """Fetch jobs from Indeed Publisher API (free, requires INDEED_PUBLISHER_ID env var from indeed.com/publisher)."""
        try:
            publisher_id = os.getenv("INDEED_PUBLISHER_ID")
            if not publisher_id:
                logger.info("Indeed Publisher ID not available (signup at indeed.com/publisher), skipping")
                return []

            session = await self._get_session()
            params = {
                "publisher": publisher_id,
                "v": "2",
                "format": "json",
                "start": start,
                "limit": 25,
                "highlight": 1,
                "latlong": 1
            }

            if query:
                params["q"] = query
            if location:
                params["l"] = location

            response = await session.get("https://api.indeed.com/ads/apisearch", params=params, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("results", [])
                logger.info(f"Indeed jobs count: {len(jobs)}")
                return [self._transform_indeed_job(job) for job in jobs]
            else:
                logger.warning(f"Indeed API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching Indeed jobs: {e}")
            return []

    def _transform_jsearch_job(self, job: Dict) -> Dict:
        """Transform JSearch job format to our schema."""
        employer = job.get("employer", {})
        salary_info = job.get("salary", {})

        salary_range = ""
        if salary_info.get("min") and salary_info.get("max"):
            salary_range = f"${salary_info['min']} - ${salary_info['max']}"
        elif salary_info.get("min"):
            salary_range = f"${salary_info['min']}+"

        return {
            "id": f"jsearch_{job.get('job_id', '')}",
            "title": job.get("job_title", ""),
            "company": employer.get("company_name", ""),
            "location": job.get("job_city", "") + ", " + job.get("job_state", "") if job.get("job_city") else "Remote",
            "description": job.get("job_description", ""),
            "requirements": ", ".join(job.get("job_required_skills", [])),
            "salary_range": salary_range,
            "job_type": job.get("job_employment_type", "Full-time"),
            "source": "JSearch",
            "source_url": job.get("job_apply_link", ""),
            "posted_at": datetime.fromisoformat(job.get("job_posted_at_datetime_utc", datetime.now().isoformat()).replace("Z", "+00:00")) if job.get("job_posted_at_datetime_utc") else datetime.now(),
            "is_remote": job.get("job_is_remote", False),
        }

    def _transform_jobdatalake_job(self, job: Dict) -> Dict:
        """Transform JobDataLake job format to our schema."""
        salary_min = job.get("salary_min_usd")
        salary_max = job.get("salary_max_usd")
        salary_range = ""
        if salary_min and salary_max:
            salary_range = f"${salary_min:,} - ${salary_max:,}"

        return {
            "id": f"jobdatalake_{job.get('handle', '')}",
            "title": job.get("title", ""),
            "company": job.get("company", {}).get("name", ""),
            "location": job.get("location", {}).get("text", "Remote"),
            "description": job.get("description", ""),
            "requirements": ", ".join(job.get("skills", [])),
            "salary_range": salary_range,
            "job_type": job.get("employment_type", "Full-time"),
            "source": "JobDataLake",
            "source_url": job.get("apply_url", ""),
            "posted_at": datetime.fromtimestamp(job.get("posted_at", 0) / 1000) if job.get("posted_at") else datetime.now(),
            "is_remote": job.get("remote_type") == "fully_remote",
        }

    def _transform_adzuna_job(self, job: Dict) -> Dict:
        """Transform Adzuna job format to our schema."""
        return {
            "id": f"adzuna_{job.get('id', '')}",
            "title": job.get("title", ""),
            "company": job.get("company", {}).get("display_name", ""),
            "location": job.get("location", {}).get("display_name", ""),
            "description": job.get("description", ""),
            "requirements": "",  # Adzuna doesn't provide structured requirements in basic results
            "salary_range": job.get("salary_min", ""),
            "job_type": job.get("contract_type", "Full-time"),
            "source": "Adzuna",
            "source_url": job.get("redirect_url", ""),
            "posted_at": datetime.fromisoformat(job.get("created", datetime.now().isoformat()).replace("Z", "+00:00")) if job.get("created") else datetime.now(),
            "is_remote": False,  # Adzuna doesn't specify remote in basic results
        }

    def _transform_indeed_job(self, job: Dict) -> Dict:
        """Transform Indeed job format to our schema."""
        return {
            "id": f"indeed_{job.get('jobkey', '')}",
            "title": job.get("jobtitle", ""),
            "company": job.get("company", ""),
            "location": job.get("formattedLocation", ""),
            "description": job.get("snippet", ""),
            "requirements": "",
            "salary_range": job.get("formattedRelativeTime", ""),
            "job_type": "Full-time",
            "source": "Indeed",
            "source_url": job.get("url", ""),
            "posted_at": datetime.fromtimestamp(job.get("date", 0)) if job.get("date") else datetime.now(),
            "is_remote": "remote" in job.get("jobtitle", "").lower() or "remote" in job.get("snippet", "").lower(),
        }
    
    def _extract_requirements_from_html(self, html: str) -> str:
        """Extract text content from HTML description."""
        if not html:
            return ""
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    

    
    async def scrape_all_jobs(self, force_refresh: bool = False) -> List[Dict]:
        """Scrape jobs from all sources and combine."""
        if not force_refresh and self._cached_jobs and self._last_fetch:
            if (datetime.now() - self._last_fetch).seconds < self.cache_ttl_seconds:
                return self._cached_jobs

        logger.info("Scraping jobs from external sources...")
        all_jobs = []

        tasks = [
            self.fetch_remotive_jobs("remote"),
            self.fetch_themuse_jobs(0),
            self.fetch_themuse_jobs(1),  # Get more jobs from page 1
            self.fetch_jsearch_jobs("developer", 1, 2),  # Requires API key, get 2 pages
            self.fetch_jobdatalake_jobs(1, 20),  # Requires API key
            self.fetch_adzuna_jobs("", "", 1),  # Requires API key
            self.fetch_indeed_jobs("", "", 0),  # Requires publisher ID
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_jobs.extend(result)

        self._cached_jobs = all_jobs
        self._last_fetch = datetime.now()
        logger.info(f"Scraped {len(all_jobs)} jobs total")

        return all_jobs


class JobService:
    """Service for job management with AI matching."""
    
    def __init__(self):
        self.scraper = JobScraper()
        self._sample_jobs = self._get_sample_jobs()
    
    def _get_sample_jobs(self) -> List[Dict]:
        return [
            {
                "id": "job_001",
                "title": "Senior Software Engineer",
                "company": "Google",
                "location": "Mountain View, CA",
                "description": "We're looking for a Senior Software Engineer to join our team. You'll work on scalable systems and collaborate with world-class engineers.",
                "requirements": "Python, Go, Kubernetes, AWS, SQL, System Design",
                "salary_range": "$150,000 - $250,000",
                "job_type": "Full-time",
                "source": "Indeed",
                "source_url": "https://example.com/jobs/google-001",
                "posted_at": datetime.now(),
                "is_remote": False,
            },
            {
                "id": "job_002",
                "title": "Frontend Developer",
                "company": "Stripe",
                "location": "Remote",
                "description": "Join our frontend team to build beautiful, performant payment interfaces. Work with React, TypeScript, and modern web technologies.",
                "requirements": "React, TypeScript, CSS, JavaScript, GraphQL",
                "salary_range": "$120,000 - $180,000",
                "job_type": "Full-time",
                "source": "Remotive",
                "source_url": "https://example.com/jobs/stripe-001",
                "posted_at": datetime.now(),
                "is_remote": True,
            },
            {
                "id": "job_003",
                "title": "Full Stack Developer",
                "company": "Netflix",
                "location": "Los Gatos, CA",
                "description": "Build and maintain critical applications that serve millions of users worldwide.",
                "requirements": "Java, React, Node.js, PostgreSQL, Microservices",
                "salary_range": "$140,000 - $220,000",
                "job_type": "Full-time",
                "source": "LinkedIn",
                "source_url": "https://example.com/jobs/netflix-001",
                "posted_at": datetime.now(),
                "is_remote": False,
            },
            {
                "id": "job_004",
                "title": "DevOps Engineer",
                "company": "AWS",
                "location": "Seattle, WA",
                "description": "Help build and maintain cloud infrastructure for Amazon's internal services.",
                "requirements": "AWS, Terraform, Docker, Kubernetes, CI/CD, Linux",
                "salary_range": "$130,000 - $200,000",
                "job_type": "Full-time",
                "source": "Indeed",
                "source_url": "https://example.com/jobs/aws-001",
                "posted_at": datetime.now(),
                "is_remote": False,
            },
            {
                "id": "job_005",
                "title": "Data Scientist",
                "company": "Meta",
                "location": "Menlo Park, CA",
                "description": "Apply machine learning to solve complex problems at scale.",
                "requirements": "Python, TensorFlow, PyTorch, SQL, Statistics, ML",
                "salary_range": "$160,000 - $280,000",
                "job_type": "Full-time",
                "source": "LinkedIn",
                "source_url": "https://example.com/jobs/meta-001",
                "posted_at": datetime.now(),
                "is_remote": False,
            },
            {
                "id": "job_006",
                "title": "Remote Python Developer",
                "company": "GitLab",
                "location": "Remote",
                "description": "Work on the DevOps platform that's used by millions of developers worldwide.",
                "requirements": "Python, Ruby, Go, Docker, Kubernetes, Git",
                "salary_range": "$100,000 - $160,000",
                "job_type": "Full-time",
                "source": "Remotive",
                "source_url": "https://example.com/jobs/gitlab-001",
                "posted_at": datetime.now(),
                "is_remote": True,
            },
            {
                "id": "job_007",
                "title": "iOS Developer",
                "company": "Apple",
                "location": "Cupertino, CA",
                "description": "Build the next generation of iOS applications.",
                "requirements": "Swift, iOS, Objective-C, Xcode, UIKit, SwiftUI",
                "salary_range": "$140,000 - $230,000",
                "job_type": "Full-time",
                "source": "Indeed",
                "source_url": "https://example.com/jobs/apple-001",
                "posted_at": datetime.now(),
                "is_remote": False,
            },
            {
                "id": "job_008",
                "title": "Backend Engineer",
                "company": "Spotify",
                "location": "Remote",
                "description": "Build services that power the world's largest music streaming platform.",
                "requirements": "Python, Scala, PostgreSQL, Kafka, Kubernetes",
                "salary_range": "$130,000 - $190,000",
                "job_type": "Full-time",
                "source": "Remotive",
                "source_url": "https://example.com/jobs/spotify-001",
                "posted_at": datetime.now(),
                "is_remote": True,
            },
        ]
    
    async def initialize(self):
        """Initialize service - scrape jobs on startup."""
        try:
            await self.scraper.scrape_all_jobs(force_refresh=True)
        except Exception as e:
            logger.warning(f"Initial job scrape failed, using samples: {e}")
    
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
        """Search jobs with filters."""
        if use_live_data:
            # Combine live jobs and sample jobs, preferring live jobs for duplicates
            live_jobs = await self.scraper.scrape_all_jobs()
            all_jobs = live_jobs + self._sample_jobs.copy()

            # Remove duplicates by ID, preferring live jobs over sample jobs
            seen_ids = set()
            jobs = []
            for job in all_jobs:
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    jobs.append(job)
        else:
            jobs = self._sample_jobs.copy()

        if query:
            query_lower = query.lower()
            jobs = [
                j for j in jobs
                if query_lower in j["title"].lower()
                or query_lower in j["company"].lower()
                or query_lower in j["description"].lower()
                or query_lower in j.get("requirements", "").lower()
            ]

        if location:
            location_lower = location.lower()
            jobs = [
                j for j in jobs
                if location_lower in j["location"].lower()
            ]

        if remote is not None:
            jobs = [j for j in jobs if j["is_remote"] == remote]

        if job_type:
            jobs = [j for j in jobs if j["job_type"] == job_type]

        start = (page - 1) * limit
        end = start + limit
        return jobs[start:end]
    
    async def match_with_resume(
        self,
        job_id: str,
        resume_content: str,
    ) -> Optional[JobMatchResponse]:
        """Match a job with a resume and return detailed results."""
        live_jobs = await self.scraper.scrape_all_jobs()
        all_jobs = live_jobs + self._sample_jobs

        # Remove duplicates by ID, preferring live jobs over sample jobs
        seen_ids = set()
        unique_jobs = []
        for job in all_jobs:
            if job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                unique_jobs.append(job)

        job = next((j for j in unique_jobs if j["id"] == job_id), None)
        if not job:
            return None
        
        resume_skills = extract_skills_from_text(resume_content)
        job_skills = extract_skills_from_text(job.get("requirements", "") + " " + job.get("description", ""))
        
        score, matched, missing = calculate_match_score(resume_skills, job_skills)
        
        return JobMatchResponse(
            id=job["id"],
            title=job["title"],
            company=job["company"],
            location=job["location"],
            description=job["description"],
            requirements=job.get("requirements"),
            salary_range=job.get("salary_range"),
            job_type=job.get("job_type"),
            source=job["source"],
            source_url=job.get("source_url"),
            posted_at=job["posted_at"],
            is_remote=job["is_remote"],
            created_at=job.get("posted_at", datetime.now()),
            match_score=score,
            matched_skills=matched,
            missing_skills=missing,
        )
    
    async def get_recommendations(
        self,
        resume_content: str,
        career_preferences: Optional[Dict] = None,
        limit: int = 6,
    ) -> List[JobMatchResponse]:
        """Get job recommendations based on resume and career preferences."""
        scraped_jobs = await self.scraper.scrape_all_jobs()
        all_jobs = scraped_jobs + self._sample_jobs
        
        if career_preferences:
            preferred_titles = career_preferences.get("preferred_titles", [])
            preferred_locations = career_preferences.get("preferred_locations", [])
            preferred_skills = career_preferences.get("preferred_skills", [])
            remote_only = career_preferences.get("remote_only", False)
            
            if preferred_titles:
                all_jobs = [
                    j for j in all_jobs
                    if any(title.lower() in j["title"].lower() for title in preferred_titles)
                ]
            
            if remote_only:
                all_jobs = [j for j in all_jobs if j.get("is_remote", False)]
            
            if preferred_locations:
                all_jobs = [
                    j for j in all_jobs
                    if any(loc.lower() in j["location"].lower() for loc in preferred_locations)
                ]
        
        recommendations = []
        for job in all_jobs:
            matched = await self.match_with_resume(job["id"], resume_content)
            if matched:
                recommendations.append(matched)
        
        recommendations.sort(key=lambda x: x.match_score or 0, reverse=True)
        return recommendations[:limit]
    
    async def get_live_job_count(self) -> int:
        """Get count of live scraped jobs."""
        jobs = await self.scraper.scrape_all_jobs()
        return len(jobs)


job_service = JobService()
