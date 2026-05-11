from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str
    ANTHROPIC_API_KEY: str

    # Cloudflare R2
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_PUBLIC_URL: str

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # URA Data Service (free key from ura.gov.sg/maps/api/)
    URA_ACCESS_KEY: str = ""

    # App
    API_BASE_URL: str = "http://localhost:8000"
    LISTING_BOOST_PRICE: int = 4900  # cents

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
