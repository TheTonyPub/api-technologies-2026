from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI()

class LoginData(BaseModel):
    UserName: str

class UpdateData(BaseModel):
    UserName: str
    NewName: str = None

@app.get("/Hello") 
async def hello():
    return {"message": "Hello"}

@app.post("/login")
async def login(data: LoginData):
    return {"message": f"Hello {data.UserName}"}

@app.put("/user/{username}")
async def update_user(username: str, data: UpdateData):
    return {
        "message": f"User {username} updated",
        "new_data": data.dict()
    }


@app.delete("/user/{username}")
async def delete_user(username: str):
    return {"message": f"User {username} deleted"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
