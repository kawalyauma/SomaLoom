import re
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

SUBJECTS = {'math':'Mathematics','maths':'Mathematics','mtc':'Mathematics','mathematics':'Mathematics',
    'science':'Integrated Science','sci':'Integrated Science','integrated science':'Integrated Science',
    'sst':'Social Studies','social studies':'Social Studies','english':'English','re':'Religious Education',
    'religious education':'Religious Education','cre':'Christian Religious Education','ire':'Islamic Religious Education'}
WORDS = ['one','two','three','four','five','six','seven']

def grade_name(value):
    value = value.strip()
    for i, word in enumerate(WORDS, 1):
        value = re.sub(r'\b'+word+r'\b', str(i), value, flags=re.I)
    match = re.fullmatch(r'(P(?:RIMARY)?|S(?:ENIOR)?)[.\s-]*([1-7])', value, re.I)
    if match:return match.group(1)[0].upper()+match.group(2)
    return {'baby class':'Baby','middle class':'Middle','top class':'Top'}.get(value.casefold(),value)

def subject_name(value):
    return SUBJECTS.get(value.strip().casefold(), value.strip())

def normalized(value):
    return re.sub(r'\s+', ' ', value).strip().casefold()

def is_scheme(title):
    text = title.casefold().replace('_',' ').replace('-',' ')
    return bool(re.search(r'\bscheme(?:s)?\b|\bsow\b',text)) and not re.search(r'marking|mscheme|loan|sponsor|examination scheme',text)

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Citation(Strict):
    block_id: UUID
    quote: str = Field(min_length=5, max_length=1200)
class Lesson(Strict):
    term: int = Field(ge=1, le=3)
    week: int = Field(ge=1, le=53)
    lesson: int = Field(ge=1, le=50)
    topic: str = Field(min_length=1,max_length=250)
    subtopic: str = Field(min_length=1,max_length=300)
    objectives: list[str] = Field(min_length=1,max_length=8)
    activities: list[str] = Field(max_length=10)
    materials: list[str] = Field(max_length=10)
    assessment: str = Field(max_length=1500)
    inferred: bool
    source: Citation
class Scheme(Strict):
    grade: str = Field(min_length=1,max_length=80)
    subject: str = Field(min_length=1,max_length=120)
    identity_quote: str = Field(min_length=2,max_length=1000)
    lessons: list[Lesson] = Field(max_length=500)
class Parsed(Strict):
    schemes: list[Scheme] = Field(max_length=30)
    warnings: list[str] = Field(max_length=30)
