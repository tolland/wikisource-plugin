from sqlmodel import Field, SQLModel, create_engine


class Namespace(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)
    name: str
    key: str
