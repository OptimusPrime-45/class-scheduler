from __future__ import annotations

from datetime import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List

from app.db import get_session
from app.models import Teacher, Batch, Subject, TeacherType, Board, SubjectDifficulty

router = APIRouter()

# --------------------------------------------------------------------------- #
# Pydantic Schemas                                                           #
# --------------------------------------------------------------------------- #

class TeacherCreate(BaseModel):
    full_name: str
    phone: str | None = None
    email: str | None = None
    teacher_type: TeacherType = TeacherType.PART_TIME
    telegram_chat_id: int | None = None
    telegram_username: str | None = None
    max_lectures_per_day: int = 6
    preferred_hours_start: time | None = None
    preferred_hours_end: time | None = None
    notes: str | None = None


class TeacherResponse(BaseModel):
    id: int
    full_name: str
    phone: str | None
    email: str | None
    teacher_type: TeacherType
    telegram_chat_id: int | None
    telegram_username: str | None
    max_lectures_per_day: int
    preferred_hours_start: time | None
    preferred_hours_end: time | None
    is_active: bool
    notes: str | None

    class Config:
        from_attributes = True


class BatchCreate(BaseModel):
    name: str
    grade: int
    board: Board


class BatchResponse(BaseModel):
    id: int
    name: str
    grade: int
    board: Board
    is_active: bool

    class Config:
        from_attributes = True


class SubjectCreate(BaseModel):
    name: str
    code: str
    difficulty: SubjectDifficulty = SubjectDifficulty.STANDARD


class SubjectResponse(BaseModel):
    id: int
    name: str
    code: str
    difficulty: SubjectDifficulty
    is_active: bool

    class Config:
        from_attributes = True


# --------------------------------------------------------------------------- #
# Teacher CRUD Routes                                                        #
# --------------------------------------------------------------------------- #

@router.post("/teachers", response_model=TeacherResponse, status_code=status.HTTP_201_CREATED)
async def create_teacher(body: TeacherCreate, session: AsyncSession = Depends(get_session)):
    teacher = Teacher(
        full_name=body.full_name,
        phone=body.phone,
        email=body.email,
        teacher_type=body.teacher_type,
        telegram_chat_id=body.telegram_chat_id,
        telegram_username=body.telegram_username,
        max_lectures_per_day=body.max_lectures_per_day,
        preferred_hours_start=body.preferred_hours_start,
        preferred_hours_end=body.preferred_hours_end,
        is_active=True,
        notes=body.notes
    )
    session.add(teacher)
    await session.commit()
    await session.refresh(teacher)
    return teacher


@router.get("/teachers/{teacher_id}", response_model=TeacherResponse)
async def get_teacher(teacher_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Teacher).filter(Teacher.id == teacher_id)
    res = await session.execute(stmt)
    teacher = res.scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher with ID {teacher_id} not found"
        )
    return teacher


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher(teacher_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Teacher).filter(Teacher.id == teacher_id)
    res = await session.execute(stmt)
    teacher = res.scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher with ID {teacher_id} not found"
        )
    await session.delete(teacher)
    await session.commit()
    return


# --------------------------------------------------------------------------- #
# Batch CRUD Routes                                                          #
# --------------------------------------------------------------------------- #

@router.post("/batches", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(body: BatchCreate, session: AsyncSession = Depends(get_session)):
    batch = Batch(
        name=body.name,
        grade=body.grade,
        board=body.board,
        is_active=True
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Batch).filter(Batch.id == batch_id)
    res = await session.execute(stmt)
    batch = res.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with ID {batch_id} not found"
        )
    return batch


@router.delete("/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch(batch_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Batch).filter(Batch.id == batch_id)
    res = await session.execute(stmt)
    batch = res.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with ID {batch_id} not found"
        )
    await session.delete(batch)
    await session.commit()
    return


# --------------------------------------------------------------------------- #
# Subject CRUD Routes                                                        #
# --------------------------------------------------------------------------- #

@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(body: SubjectCreate, session: AsyncSession = Depends(get_session)):
    subject = Subject(
        name=body.name,
        code=body.code,
        difficulty=body.difficulty,
        is_active=True
    )
    session.add(subject)
    await session.commit()
    await session.refresh(subject)
    return subject


@router.get("/subjects/{subject_id}", response_model=SubjectResponse)
async def get_subject(subject_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Subject).filter(Subject.id == subject_id)
    res = await session.execute(stmt)
    subject = res.scalar_one_or_none()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with ID {subject_id} not found"
        )
    return subject


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(subject_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Subject).filter(Subject.id == subject_id)
    res = await session.execute(stmt)
    subject = res.scalar_one_or_none()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with ID {subject_id} not found"
        )
    await session.delete(subject)
    await session.commit()
    return
