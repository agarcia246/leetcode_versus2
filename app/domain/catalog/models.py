"""Catalog domain tables: problems, topics, and their links (Research/Database.png)."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Problem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    lc_id = Column(String, nullable=False, unique=True)
    lc_url = Column(String, nullable=False)
    difficulty = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "difficulty IN ('Easy', 'Medium', 'Hard')",
            name="check_problem_difficulty",
        ),
    )

    topic_links = relationship("ProblemTopic", back_populates="problem")


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_name = Column(String, nullable=False, unique=True)

    problem_links = relationship("ProblemTopic", back_populates="topic")


class ProblemTopic(Base):
    __tablename__ = "problem_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    problem_id = Column(
        Integer,
        ForeignKey("problems.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("problem_id", "topic_id"),)

    problem = relationship("Problem", back_populates="topic_links")
    topic = relationship("Topic", back_populates="problem_links")
