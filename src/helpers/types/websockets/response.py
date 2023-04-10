from typing import Optional

from pydantic import BaseModel, Extra

from src.helpers.types.websockets.common import Id, SeqId, SubscriptionId, Type


class ResponseMessage(BaseModel):
    """Message part of the websocket response"""

    class Config:
        extra = Extra.allow


class WebsocketResponse(BaseModel):
    id: Optional[Id]
    seq: Optional[SeqId]
    sid: Optional[SubscriptionId]
    type: Type
    msg: ResponseMessage

    class Config:
        use_enum_values = True

    def convert_msg(self, type: BaseModel):
        """Converts the response's message to a specific response type"""
        self.msg = type.parse_obj(self.msg)


##### Different type of response messages ####


class ErrorResponse(ResponseMessage):
    code: int
    msg: str
