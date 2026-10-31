from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from .db import Base

def now(): return datetime.now(timezone.utc)
class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True); email=Column(String(250),unique=True,nullable=False,index=True)
    password_hash=Column(Text,nullable=False); created_at=Column(DateTime(timezone=True),default=now)
class Invite(Base):
    __tablename__='invites'
    id=Column(Integer,primary_key=True); token_hash=Column(String(64),unique=True,nullable=False)
    used_by=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=True); created_at=Column(DateTime(timezone=True),default=now)
class Session(Base):
    __tablename__='sessions'
    id=Column(Integer,primary_key=True); token_hash=Column(String(64),unique=True,index=True,nullable=False)
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False)
    csrf_hash=Column(String(64),nullable=False); expires_at=Column(DateTime(timezone=True),nullable=False)
class Project(Base):
    __tablename__='projects'
    id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    title=Column(String(240),nullable=False); kind=Column(String(32),nullable=False)
    premise=Column(Text,default='',nullable=False); structure=Column(Text,default='{}',nullable=False)
    scratchpad=Column(Text,default='',nullable=False); checkpoint=Column(Text,default='{}',nullable=False)
    version=Column(Integer,default=1,nullable=False); created_at=Column(DateTime(timezone=True),default=now); updated_at=Column(DateTime(timezone=True),default=now)
    sections=relationship('Section',cascade='all, delete-orphan',passive_deletes=True)
class Section(Base):
    __tablename__='sections'
    id=Column(Integer,primary_key=True); project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    title=Column(String(240),nullable=False); body=Column(Text,default='',nullable=False)
    blocks=Column(Text,default='[]',nullable=False); position=Column(Integer,default=0,nullable=False)
    version=Column(Integer,default=1,nullable=False); updated_at=Column(DateTime(timezone=True),default=now)
class Revision(Base):
    __tablename__='revisions'
    id=Column(Integer,primary_key=True); section_id=Column(Integer,ForeignKey('sections.id',ondelete='CASCADE'),nullable=False,index=True)
    version=Column(Integer,nullable=False); title=Column(String(240),nullable=False)
    body=Column(Text,default='',nullable=False); blocks=Column(Text,default='[]',nullable=False)
    created_at=Column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('section_id','version',name='uq_section_revision'),)
class Fact(Base):
    __tablename__='facts'
    id=Column(Integer,primary_key=True); project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    subject=Column(String(200),nullable=False); predicate=Column(String(200),nullable=False); value=Column(String(500),nullable=False)
    evidence=Column(Text,default='',nullable=False); section_id=Column(Integer,ForeignKey('sections.id',ondelete='SET NULL'),nullable=True)
    evidence_status=Column(String(32),default='manual',nullable=False); source_version=Column(Integer,nullable=True)
class Chat(Base):
    __tablename__='chats'
    id=Column(Integer,primary_key=True); project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    role=Column(String(12),nullable=False); text=Column(Text,nullable=False); proposals=Column(Text,default='[]',nullable=False)
    created_at=Column(DateTime(timezone=True),default=now)
