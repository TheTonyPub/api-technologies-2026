from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
from uuid import uuid4

users = {0: {'age': 30, 'sex': 'male'}}
app = FastAPI()


class UserData(BaseModel):
    age: int = Field(ge=6, le=90)
    sex: str = Field(examples=["male"])


class UserCreated(BaseModel):
    user_id: int

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/user/{user_id}")
async def get_user_info(user_id: int, payload: UserData) -> UserCreated:
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id] = {"age": payload.age, "sex": payload.sex}
    return users.get(user_id)


@app.post('/user/{user_id}')
async def create_user(user_id: int, payload: UserData) -> UserCreated: 
    if user_id in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[user_id] = {"age": payload.age, "sex": payload.sex}
    return {"user_id": uuid4().int}

@app.put('/user/{user_id}')
async def update_user(user_id:int, payload: UserData) -> UserData:
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    users[user_id] = {"age": payload.age, "sex": payload.sex}
    return payload

@app.delete('/user/{user_id}')
async def delete_user(user_id:int) -> None:
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    del users[user_id]
    return None

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)