from pydantic import BaseModel
from voc_common import HitlTask

from api_backend.auth.roles import Role


class MeResponse(BaseModel):
    email: str
    actor_hash: str
    roles: list[Role]
    reviewer_tasks: list[HitlTask]
    environment: str
    commit: str
