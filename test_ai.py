import asyncio
import os
from app.services.ai_analysis import ResumeAnalysisService
from app.core.config import settings

async def test_groq():
    print(f"Testing Groq with API Key: {settings.GROQ_API_KEY[:10]}...")
    service = ResumeAnalysisService()
    try:
        result = await service.analyze_resume("This is a test resume content for a software engineer.")
        print("Groq Success!")
        print(result)
    except Exception as e:
        print(f"Groq Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_groq())
