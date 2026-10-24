from fastapi import FastAPI

from app.api import auth, categories, health, issues, members, priority

app = FastAPI(
    title="FlowOps API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(issues.router, prefix="/api")
app.include_router(priority.router, prefix="/api")
