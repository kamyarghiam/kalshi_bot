from pydantic import BaseModel


class ExternalApi(BaseModel):
    """This class is a type for api requests and responses"""


class Cursor(str):
    """The Cursor represents a pointer to the next page of records in the pagination.
    Use the value returned here in the cursor query parameter for this end-point to get
    the next page containing limit records. An empty value of this field indicates there
    is no next page.
    """
