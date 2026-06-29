from wtbot.model.sqlmodel import Page
from fastapi import FastAPI
from sqlmodel import Field, SQLModel, create_engine, Session, select
from wtbot.model import sqlmodel

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=True)


def create_db_and_tables():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

app = FastAPI()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.post("/page/")
def create_page(page: Page):
    with Session(engine) as session:
        session.add(page)
        session.commit()
        session.refresh(page)
        return page


@app.get("/pages/")
def read_pages():
    with Session(engine) as session:
        pages = session.exec(select(Page)).all()
        return pages
