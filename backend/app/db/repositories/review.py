"""Manual links and exclusions: what a dry-run review changes for every later run."""

import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CommitExclusion, CommitLink


class ReviewRepository:
    """One project's links and exclusions. The caller has already checked access."""

    def __init__(self, session: Session, project_id: uuid.UUID) -> None:
        self.session = session
        self.project_id = project_id

    def links(self, shas: list[str] | None = None) -> dict[str, list[int]]:
        """Work items linked by hand, per commit, in the order they were linked."""
        query = select(CommitLink.commit_sha, CommitLink.work_item_id).where(
            CommitLink.project_id == self.project_id
        )
        if shas is not None:
            query = query.where(CommitLink.commit_sha.in_(shas))
        result: dict[str, list[int]] = defaultdict(list)
        for sha, work_item_id in self.session.execute(query.order_by(CommitLink.created_at)):
            result[sha].append(work_item_id)
        return dict(result)

    def exclusions(self, shas: list[str] | None = None) -> set[tuple[str, int]]:
        query = select(CommitExclusion.commit_sha, CommitExclusion.work_item_id).where(
            CommitExclusion.project_id == self.project_id
        )
        if shas is not None:
            query = query.where(CommitExclusion.commit_sha.in_(shas))
        return {(sha, work_item_id) for sha, work_item_id in self.session.execute(query)}

    def _add(
        self,
        model: type[CommitLink] | type[CommitExclusion],
        sha: str,
        work_item_id: int,
        by: uuid.UUID,
    ) -> None:
        statement = insert(model).values(
            id=uuid.uuid4(),
            project_id=self.project_id,
            commit_sha=sha,
            work_item_id=work_item_id,
            created_by_id=by,
        )
        self.session.execute(statement.on_conflict_do_nothing())

    def link(self, sha: str, work_item_id: int, by: uuid.UUID) -> None:
        self._add(CommitLink, sha, work_item_id, by)

    def unlink(self, sha: str, work_item_id: int) -> None:
        self.session.execute(
            delete(CommitLink).where(
                CommitLink.project_id == self.project_id,
                CommitLink.commit_sha == sha,
                CommitLink.work_item_id == work_item_id,
            )
        )

    def exclude(self, sha: str, work_item_id: int, by: uuid.UUID) -> None:
        self._add(CommitExclusion, sha, work_item_id, by)

    def include(self, sha: str, work_item_id: int) -> None:
        self.session.execute(
            delete(CommitExclusion).where(
                CommitExclusion.project_id == self.project_id,
                CommitExclusion.commit_sha == sha,
                CommitExclusion.work_item_id == work_item_id,
            )
        )
