from itertools import count

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Books API")


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100, examples=["Harry Potter"])
    author: str = Field(min_length=1, max_length=100, examples=["Joanne Rowling"])
    isbn: str = Field(pattern=r"^97[89]\d{10}$", examples=["9780747532699"])


class BookUpdate(BaseModel):
    title: str | None = Field(min_length=1, max_length=100, examples=["Harry Potter"], default=None)
    author: str | None = Field(min_length=1, max_length=100, examples=["Joanne Rowling"], default=None)
    isbn: str | None = Field(pattern=r"^97[89]\d{10}$", examples=["9780747532699"], default=None)


class BookResponse(BookCreate):
    book_id: int


class BookCreated(BaseModel):
    book_id: int


books_db: dict[int, BookResponse] = {}
book_ids = count(1)


@app.post("/books", status_code=201, response_model=BookCreated)
def create_book(book: BookCreate):
    book_id = next(book_ids)
    books_db[book_id] = BookResponse(book_id=book_id, **book.model_dump())
    return BookCreated(book_id=book_id)


@app.get("/books/{book_id}", response_model=BookResponse)
def get_book(book_id: int):
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    return books_db[book_id]


@app.put("/books/{book_id}", response_model=BookResponse)
def update_book(book_id: int, changes: BookUpdate):
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    old = books_db[book_id].model_dump()
    new = changes.model_dump(exclude_none=True)
    books_db[book_id] = BookResponse(**(old | new))
    return books_db[book_id]


@app.delete("/books/{book_id}", status_code=204)
def delete_book(book_id: int):
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    del books_db[book_id]
