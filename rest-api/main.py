from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn
from typing import Optional

app = FastAPI()

class LoginData(BaseModel):
    UserName: str = Field(..., min_length=3, max_length=50)

class UpdateData(BaseModel):
    UserName: str = Field(..., min_length=3, max_length=50)
    NewName: Optional[str] = Field(None, min_length=3, max_length=50)

class MessageResponse(BaseModel):
    message: str

@app.get("/items", response_model=MessageResponse)
async def get_item(item_id: int):
    return {"message": f"Item {item_id}"}

@app.post("/items", response_model=MessageResponse)
async def create_item(data: LoginData):
    return {"message": f"Hello {data.UserName}"}

@app.put("/items/{item_id}", response_model=MessageResponse)
async def update_item(item_id: int, data: UpdateData):
    return {"message": f"Item {item_id} updated to {data.NewName or data.UserName}"}


@app.delete("/items/{item_id}", response_model=MessageResponse)
async def delete_item(item_id: int):
    return {"message": f"Item {item_id} deleted"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
