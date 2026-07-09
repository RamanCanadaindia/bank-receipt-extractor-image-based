from tasks.google_search import GoogleSearchTask
from tasks.website_scraper import WebsiteScraperTask
from tasks.competitor_research import CompetitorResearchTask
from tasks.custom_url_task import CustomUrlTask
from tasks.flight_search import FlightSearchTask

TASK_MAPPING = {
    "google_search": GoogleSearchTask,
    "website_scraper": WebsiteScraperTask,
    "competitor_research": CompetitorResearchTask,
    "custom_url_task": CustomUrlTask,
    "flight_search": FlightSearchTask
}
