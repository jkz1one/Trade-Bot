from __future__ import annotations
from abc import ABC, abstractmethod
from app.domain.models import Candidate

class UniverseProvider(ABC):
    @abstractmethod
    def candidates(self) -> list[Candidate]: ...
