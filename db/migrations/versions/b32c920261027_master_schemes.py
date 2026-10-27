"""Add durable scheme imports and per-class subject master schedules."""
from alembic import op
import sqlalchemy as sa
revision = 'b32c920261027'
down_revision = 'a7ddca613219'
branch_labels = None
depends_on = None

def upgrade():
    for name, fields, links, unique in (
        ('scheme_imports', [('parser_version',sa.String(40)),('stage',sa.String(40)),('payload',sa.JSON())], [('resource_version_id','resource_versions'),('job_id','background_jobs')], ['tenant_id','resource_version_id','parser_version']),
        ('master_schemes', [('grade',sa.String(80)),('subject',sa.String(120)),('body',sa.JSON())], [('curriculum_id','curricula')], ['tenant_id','grade','subject']),
    ):
        columns=[sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),sa.ForeignKey('schools.id'),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('id','tenant_id')]
        columns += [sa.Column(field,kind,nullable=False) for field,kind in fields]
        for field,target in links:
            columns.extend([sa.Column(field,sa.Uuid(),nullable=False),sa.ForeignKeyConstraint([field,'tenant_id'],[target+'.id',target+'.tenant_id'])])
        op.create_table(name,*columns,sa.UniqueConstraint(*unique))
        op.create_index('ix_'+name+'_tenant_id',name,['tenant_id'])

def downgrade():
    for name in ('master_schemes','scheme_imports'):
        op.drop_table(name)
