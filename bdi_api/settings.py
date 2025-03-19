from os.path import dirname, join
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import bdi_api
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define the project directory
PROJECT_DIR = dirname(dirname(bdi_api.__file__))

class Settings(BaseSettings):
    source_url: str = Field(
        default="https://samples.adsbexchange.com/readsb-hist",
        description="Base URL to the website used to download the data.",
    )
    local_dir: str = Field(
        default=join(PROJECT_DIR, "data"),
        description="For any other value set env variable 'BDI_LOCAL_DIR'",
    )
    s3_bucket: str = Field(
        default=os.getenv("S3_BUCKET", "bdi-aircraft-luis-canas"),  # Default bucket
        description="S3 bucket name.",
    )
    s3_key_id: str = Field(
        default=os.getenv("AWS_ACCESS_KEY_ID", ""),
        description="AWS Access Key ID",
    )
    s3_access_key: str = Field(
        default=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        description="AWS Secret Access Key",
    )
    s3_session_token: str = Field(
        default=os.getenv("AWS_SESSION_TOKEN", ""),
        description="AWS Session Token (if using temporary credentials)",
    )
    s3_region: str = Field(
        default=os.getenv("AWS_REGION", "us-east-1"),
        description="AWS region",
    )

    telemetry: bool = False
    telemetry_dsn: str = "http://project2_secret_token@uptrace:14317/2"

    model_config = SettingsConfigDict(env_prefix="bdi_")

    @property
    def raw_dir(self) -> str:
        """Store inside all the raw JSONs"""
        return join(self.local_dir, "raw")

    @property
    def prepared_dir(self) -> str:
        """Store inside all the processed data"""
        return join(self.local_dir, "prepared")


class DBCredentials:
    """Database credentials loaded from environment variables"""

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_NAME = os.getenv("DB_NAME", "bdi_aircraft")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", None)
    DB_PORT = int(os.getenv("DB_PORT", 5432))

    # Ensure all expected attributes exist
    database = DB_NAME  # Alias for compatibility
    username = DB_USER  # Alias for username
    password = DB_PASSWORD  # Alias for password
    host = DB_HOST  # Alias for host
    port = DB_PORT  # Alias for port

    @classmethod
    def get_connection_url(cls):
        """Returns the PostgreSQL connection string."""
        return f"postgresql://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"

    @classmethod
    def debug_credentials(cls):
        """Prints credentials for debugging."""
        print("== DB Credentials Debug ==")
        print(f"Host: {cls.host}")
        print(f"Database: {cls.database}")
        print(f"User: {cls.username}")
        print(f"Password: {'********' if cls.password else 'NOT SET'}")  # Hide password in logs
        print(f"Port: {cls.port}")
        print("=========================")

