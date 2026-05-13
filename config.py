
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WELCOME_IMAGE_URL = os.getenv(
    "WELCOME_IMAGE_URL",
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30"
)

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]
