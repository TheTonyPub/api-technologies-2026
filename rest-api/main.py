from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Movie Service")


class MovieCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150, examples=["Interstellar"])
    year: int = Field(ge=1888, le=2030, examples=[2014])
    rating: float = Field(ge=0, le=10, examples=[8.7])


class MovieUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150, examples=["Inception"])
    year: int | None = Field(default=None, ge=1888, le=2030, examples=[2010])
    rating: float | None = Field(default=None, ge=0, le=10, examples=[8.8])


class MovieCreated(BaseModel):
    movie_id: str


class Movie(MovieCreate):
    movie_id: str


movies: dict[str, Movie] = {}


def find_movie(movie_id: str) -> Movie:
    if movie_id not in movies:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movies[movie_id]


@app.post("/api/movies", status_code=201, response_model=MovieCreated)
def add_movie(data: MovieCreate):
    movie_id = str(uuid4())
    movies[movie_id] = Movie(movie_id=movie_id, **data.model_dump())
    return {"movie_id": movie_id}


@app.get("/api/movies/{movie_id}", response_model=Movie)
def read_movie(movie_id: str):
    return find_movie(movie_id)


@app.put("/api/movies/{movie_id}", response_model=Movie)
def edit_movie(movie_id: str, data: MovieUpdate):
    movie = find_movie(movie_id)
    movies[movie_id] = movie.model_copy(update=data.model_dump(exclude_none=True))
    return movies[movie_id]


@app.delete("/api/movies/{movie_id}", status_code=204)
def remove_movie(movie_id: str):
    if movies.pop(movie_id, None) is None:
        raise HTTPException(status_code=404, detail="Movie not found")
