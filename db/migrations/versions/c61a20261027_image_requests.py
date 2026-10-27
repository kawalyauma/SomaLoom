"""Persist image prompts and imported illustrations."""
from alembic import op
import sqlalchemy as sa
revision='c61a20261027'
down_revision='b32c920261027'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('image_requests',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),sa.ForeignKey('schools.id'),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('title',sa.String(250),nullable=False),sa.Column('prompt',sa.Text(),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('metadata',sa.JSON(),nullable=False),sa.Column('requested_by',sa.Uuid(),nullable=False),sa.Column('generation_job_id',sa.Uuid(),nullable=True),sa.UniqueConstraint('id','tenant_id'),sa.ForeignKeyConstraint(['requested_by','tenant_id'],['users.id','users.tenant_id']),sa.ForeignKeyConstraint(['generation_job_id','tenant_id'],['generation_jobs.id','generation_jobs.tenant_id']))
    op.create_index('ix_image_requests_tenant_id','image_requests',['tenant_id'])

def downgrade():op.drop_table('image_requests')
