"""Pydantic schemas untuk REST API dashboard."""

from typing import Any, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class DeviceInfo(BaseModel):
    name: str
    id: str
    type: str
    status: str
    dps_switch: int


class DeviceListResponse(BaseModel):
    devices: list[DeviceInfo]


class ControlResponse(BaseModel):
    success: bool
    message: str
    no_op: bool = False


class DeviceStatusResponse(BaseModel):
    success: bool
    name: str
    online: bool
    switch_on: Optional[bool] = None
    dps: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class PowerInfoResponse(BaseModel):
    success: bool
    power_w: float = 0
    current_a: float = 0
    voltage_v: float = 0
    switch_on: Optional[bool] = None
    message: Optional[str] = None
