from enum import Enum

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Chebupizza diary")

CALORIES_PER_PIECE = 270


class Flavor(str, Enum):
    classic = "classic"
    cheese = "cheese"
    pepperoni = "pepperoni"


class MealRequest(BaseModel):
    flavor: Flavor = Field(examples=["classic"])
    pieces: int = Field(ge=1, le=50, examples=[3])
    eaten_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2026-10-12"])
    comment: str = Field(min_length=1, max_length=200, examples=["после пары"])


class MealResponse(BaseModel):
    id: int
    flavor: Flavor
    pieces: int
    eaten_at: str
    comment: str


class StatsResponse(BaseModel):
    meals: int
    total_pieces: int
    total_calories: int
    average_pieces: float
    favorite_flavor: str


meals: dict[int, MealResponse] = {}
next_id = 1


@app.get("/v1/meals")
def get_meals() -> list[MealResponse]:
    return list(meals.values())


@app.get("/v1/stats")
def get_stats() -> StatsResponse:
    total = 0
    by_flavor = {}
    for meal in meals.values():
        total += meal.pieces
        by_flavor[meal.flavor.value] = by_flavor.get(meal.flavor.value, 0) + meal.pieces

    if len(meals) == 0:
        return StatsResponse(meals=0, total_pieces=0, total_calories=0, average_pieces=0, favorite_flavor="-")

    favorite = max(by_flavor, key=by_flavor.get)
    return StatsResponse(
        meals=len(meals),
        total_pieces=total,
        total_calories=total * CALORIES_PER_PIECE,
        average_pieces=round(total / len(meals), 2),
        favorite_flavor=favorite,
    )


@app.post("/v1/meal", status_code=201)
def create_meal(meal: MealRequest) -> MealResponse:
    global next_id
    new_meal = MealResponse(
        id=next_id,
        flavor=meal.flavor,
        pieces=meal.pieces,
        eaten_at=meal.eaten_at,
        comment=meal.comment,
    )
    meals[next_id] = new_meal
    next_id += 1
    return new_meal


@app.get("/v1/meal/{meal_id}")
def get_meal(meal_id: int) -> MealResponse:
    if meal_id not in meals:
        raise HTTPException(status_code=404, detail="Meal not found")
    return meals[meal_id]


@app.put("/v1/meal/{meal_id}")
def update_meal(meal_id: int, meal: MealRequest) -> MealResponse:
    if meal_id not in meals:
        raise HTTPException(status_code=404, detail="Meal not found")
    meals[meal_id] = MealResponse(
        id=meal_id,
        flavor=meal.flavor,
        pieces=meal.pieces,
        eaten_at=meal.eaten_at,
        comment=meal.comment,
    )
    return meals[meal_id]


@app.delete("/v1/meal/{meal_id}", status_code=204)
def delete_meal(meal_id: int):
    if meal_id not in meals:
        raise HTTPException(status_code=404, detail="Meal not found")
    meals.pop(meal_id)
