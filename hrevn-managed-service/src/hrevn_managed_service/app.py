from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.baseline import router as baseline_router
from .api.bundles import router as bundles_router
from .api.company_account import router as company_account_router
from .api.company_training import router as company_training_router
from .api.course import router as course_router
from .api.health import router as health_router
from .api.junta_demo import router as junta_demo_router
from .api.leads import router as leads_router
from .api.policy import router as policy_router
from .api.promotora_demo import router as promotora_demo_router
from .api.property_demo import router as property_demo_router
from .api.version import router as version_router
from .config import settings


app = FastAPI(title=settings.service_name, version=settings.service_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.lead_allowed_origins,
    allow_origin_regex=settings.lead_allowed_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(version_router)
app.include_router(baseline_router)
app.include_router(bundles_router)
app.include_router(company_account_router)
app.include_router(company_training_router)
app.include_router(course_router)
app.include_router(policy_router)
app.include_router(leads_router)
app.include_router(property_demo_router)
app.include_router(junta_demo_router)
app.include_router(promotora_demo_router)
