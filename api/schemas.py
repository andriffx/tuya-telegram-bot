"""Pydantic schemas untuk REST API dashboard."""

from typing import Any

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
    switch_on: bool | None = None
    dps: dict[str, Any] | None = None
    message: str | None = None


class PowerInfoResponse(BaseModel):
    success: bool
    power_w: float = 0
    current_a: float = 0
    voltage_v: float = 0
    switch_on: bool | None = None
    message: str | None = None
