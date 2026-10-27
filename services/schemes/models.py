from sqlalchemy import JSON, String, UniqueConstraint
from app.core.models import col, domain

imports = domain('scheme_imports', [
    col('parser_version', String(40)), col('stage', String(40)), col('payload', JSON),
], [('resource_version_id', 'resource_versions'), ('job_id', 'background_jobs')])
imports.append_constraint(UniqueConstraint('tenant_id', 'resource_version_id', 'parser_version'))
masters = domain('master_schemes', [
    col('grade', String(80)), col('subject', String(120)), col('body', JSON),
], [('curriculum_id', 'curricula')])
masters.append_constraint(UniqueConstraint('tenant_id', 'grade', 'subject'))
