import asyncio
import json
import re
import httpx
import logging
from datetime import datetime
from typing import List, Optional, Dict, Set
from app.schemas.job import JobCreate, JobMatchResponse
from app.models.job import Job

logger = logging.getLogger(__name__)

COMMON_SKILLS = {
    "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#",
    "react", "vue", "angular", "next.js", "node.js", "express", "django", "flask",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "jenkins",
    "sql", "postgresql", "mysql", "mongodb", "redis", "graphql", "rest",
    "machine learning", "tensorflow", "pytorch", "nlp", "data science",
    "git", "linux", "agile", "scrum", "ci/cd", "devops",
    "swift", "ios", "android", "flutter", "react native",
    "sass", "css", "html", "tailwind", "figma",
    "spark", "hadoop", "kafka", "airflow", "etl",
    "microservices", "api", "system design", "architecture",
    "postgresql", "mongodb", "redis", "graphql", "rest api",
    "typescript", "sass", "css", "html", "tailwindcss", "figma",
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
        return 50, [], []
    
    matched = resume_skills.intersection(job_skills)
    missing = job_skills - resume_skills
    
    if not job_skills:
        return 0, [], []
    
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
    
    async def fetch_remoteok_jobs(self, tag: str = "remote") -> List[Dict]:
        """Fetch jobs from RemoteOK API (free, no auth required)."""
        try:
            session = await self._get_session()
            url = f"https://remoteok.com/api?tag={tag}"
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                text = response.text
                return self._parse_remoteok_jobs(text)
            else:
                logger.warning(f"RemoteOK API returned status {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching RemoteOK jobs: {e}")
            return []
    
    def _parse_remoteok_jobs(self, text: str) -> List[Dict]:
        """Parse RemoteOK JSON response from text."""
        jobs = []
        try:
            data = json.loads(text)
            for job in data:
                if job.get("id") and job.get("position"):
                    jobs.append(self._transform_remoteok_job(job))
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing RemoteOK jobs: {e}")
        return jobs
    
    def _transform_remoteok_job(self, job: Dict) -> Dict:
        """Transform RemoteOK job format to our schema."""
        return {
            "id": f"remoteok_{job.get('id', '')}",
            "title": job.get("position", ""),
            "company": job.get("company", ""),
            "location": job.get("location", "Remote"),
            "description": job.get("description", ""),
            "requirements": ", ".join(job.get("tags", [])),
            "salary_range": self._extract_salary(job.get("salary", "")),
            "job_type": "Full-time",
            "source": "RemoteOK",
            "source_url": f"https://remoteok.com/l/{job.get('id', '')}",
            "posted_at": datetime.fromtimestamp(job.get("date", 0)) if job.get("date") else datetime.now(),
            "is_remote": True,
        }
    
    def _extract_salary(self, salary_str: str) -> str:
        """Extract salary range from RemoteOK format."""
        if not salary_str:
            return ""
        return salary_str.replace("$", "$").replace("USD", "")
    
    def _extract_requirements_from_html(self, html: str) -> str:
        """Extract text content from HTML description."""
        if not html:
            return ""
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    async def fetch_indeed_jobs(self, query: str, location: str = "remote", limit: int = 10) -> List[Dict]:
        """Fetch jobs from Indeed (requires scraping, limited)."""
        try:
            session = await self._get_session()
            url = f"https://www.indeed.com/jobs?q={query}&l={location}&limit={limit}"
            response = await session.get(url, timeout=httpx.Timeout(30.0))
            if response.status_code == 200:
                html = response.text
                return self._parse_indeed_jobs(html, query)
            return []
        except Exception as e:
            logger.error(f"Error fetching Indeed jobs: {e}")
            return []
    
    def _parse_indeed_jobs(self, html: str, query: str) -> List[Dict]:
        """Parse Indeed job listings from HTML."""
        jobs = []
        try:
            import re
            job_cards = re.findall(r'job-card-container[^>]*data-jk="([^"]+)"[^>]*>(.*?)</div>', html, re.DOTALL)
            for jk, card_html in job_cards[:10]:
                title_match = re.search(r'jobTitle[^>]*>([^<]+)<', card_html)
                company_match = re.search(r'companyName[^>]*>([^<]+)<', card_html)
                location_match = re.search(r'companyLocation[^>]*>([^<]+)<', card_html)
                summary_match = re.search(r'jobSnippet[^>]*>([^<]+)<', card_html)
                
                if title_match:
                    jobs.append({
                        "id": f"indeed_{jk}",
                        "title": title_match.group(1).strip(),
                        "company": company_match.group(1).strip() if company_match else "Unknown",
                        "location": location_match.group(1).strip() if location_match else "Remote",
                        "description": summary_match.group(1).strip() if summary_match else "",
                        "requirements": "",
                        "salary_range": "",
                        "job_type": "Full-time",
                        "source": "Indeed",
                        "source_url": f"https://www.indeed.com/viewjob?jk={jk}",
                        "posted_at": datetime.now(),
                        "is_remote": "remote" in location_match.group(1).lower() if location_match else False,
                    })
        except Exception as e:
            logger.error(f"Error parsing Indeed jobs: {e}")
        return jobs
    
    async def scrape_all_jobs(self, force_refresh: bool = False) -> List[Dict]:
        """Scrape jobs from all sources and combine."""
        if not force_refresh and self._cached_jobs and self._last_fetch:
            if (datetime.now() - self._last_fetch).seconds < self.cache_ttl_seconds:
                return self._cached_jobs
        
        logger.info("Scraping jobs from external sources...")
        all_jobs = []
        
        tasks = [
            self.fetch_remotive_jobs("remote"),
            self.fetch_remoteok_jobs("remote"),
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
