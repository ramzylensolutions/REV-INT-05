from pydantic_settings import BaseSettings, SettingsConfigDict
class settings(BaseSettings):
    db_name : str
    db_pass:str
    db_user:str
    db_host:str
    db_port:int
    api_token:str
    AUDIT_BUCKET_NAME:str
    model_config=SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )
Settings = settings()