from os.path import dirname, join
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import bdi_api

# Define the project directory
PROJECT_DIR = dirname(dirname(bdi_api.__file__))

class Settings(BaseSettings):
    source_url: str = Field(
        default="https://samples.adsbexchange.com/readsb-hist",
        description="Base URL to the website used to download the data.",
    )
    local_dir: str = Field(
        default=join(PROJECT_DIR, "data"),
        description="Directory to store local data",
    )
    s3_bucket: str = Field(
        default="bdi-aircraft-luis-canas",
        description="S3 bucket name.",
    )
    s3_key_id: str = Field(
        default="",
        description="AWS Access Key ID",
    )
    s3_access_key: str = Field(
        default="",
        description="AWS Secret Access Key",
    )
    s3_session_token: str = Field(
        default="",
        description="AWS Session Token (if using temporary credentials)",
    )
    s3_region: str = Field(
        default="us-east-1",
        description="AWS region",
    )

    telemetry: bool = False
    telemetry_dsn: str = "http://project2_secret_token@uptrace:14317/2"

    model_config = SettingsConfigDict(env_prefix="bdi_")

    @property
    def raw_dir(self) -> str:
        return join(self.local_dir, "raw")

    @property
    def prepared_dir(self) -> str:
        return join(self.local_dir, "prepared")


class DBCredentials:
    """Database credentials (hardcoded)"""

    host = "localhost"
    database = "postgres"
    username = "postgres"
    password = "postgres"
    port = 5432

    @classmethod
    def get_connection_url(cls):
        return f"postgresql://{cls.username}:{cls.password}@{cls.host}:{cls.port}/{cls.database}"

    @classmethod
    def debug_credentials(cls):
        print("== DB Credentials Debug ==")
        print(f"Host: {cls.host}")
        print(f"Database: {cls.database}")
        print(f"User: {cls.username}")
        print(f"Password: {'********'}")
        print(f"Port: {cls.port}")
        print("=========================")
