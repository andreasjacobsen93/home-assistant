import asyncio
import logging

import voluptious as voluptious

from homeassistant.core import callback
from homeassistant.core import switch
from homeassistant.components.climate import (
    STATE_COOL, STATE_IDLE, ClimateDevice, PLATFORM_SCHEMA,
    STATE_AUTO)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, STATE_ON, STATE_OFF, ATTR_TEMPERATURE,
    CONF_NAME)
from homeassistant.helpers import condition
from homeassistant.helpers.event import (
    async_track_state_change)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['switch', 'sensor']

DEFAULT_NAME = 'Generic Fan'

CONF_FAN = 'fan'
CONF_SENSOR = 'target_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_FAN): cv.entity_id,
    vol.Required(CONF_SENSOR): cv.entity_id,
    vol.Required(CONF_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    name = config.get(CONF_NAME)
    fan_entity_id = config.get(CONF_FAN)
    sensor_entity_id = config.get(CONF_SENSOR)
    max_temp = config.get(CONF_MAX_TEMP)
    min_temp = config.get(CONF_MIN_TEMP)

    async_add_devices([GenericFan(hass, name, fan_entity_id, sensor_entity_id, max_temp, min_temp)])

class GenericFan(ClimateDevice):

    def __init__ (self, hass, name, fan_entity_id, sensor_entity_id, max_temp, min_temp):
        self.hass = hass
        self._name = name
        self.fan_entity_id = fan_entity_id
        self._enabled = True
        self._active = False
        self._cur_temp = None
        self._max_temp = max_temp
        self._min_temp = min_temp
        self._unit = hass.config.units.temperature_unit

        async_track_state_change(hass, sensor_entity_id, self._async_sensor_changed)
        async_track_state_change(hass, fan_entity_id, self._async_sensor_changed)

        sensor_state = hass.states.get(sensor_entity_id)

        if sensor_state:
            self._async_update_temp(sensor_state)

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def temperature_unit(self):
        return self._unit

    @property
    def current_temperature(self):
        return self._cur_temp

    @property
    def current_operation(self):
        if not self._enabled:
            return STATE_OFF

        cooling = self._active and self._is_device_active
        return STATE_COOL if cooling else STATE_IDLE

    @property
    def operation_list(self):
        return [STATE_AUTO, STATE_OFF]

    @property
    def set_operation_mode(self, operation_mode):
        if operation_mode == STATE_AUTO:
            self._enabled = True
        elif operation_mode == STATE_OFF:
            self._enabled = False
            if self._is_device_active:
                switch.async_turn_off(self.hass, self.fan_entity_id)
        else:
            _LOGGER.error('Unrecognized operation mode: %s', operation_mode)

        self.schedule_update_ha_state()

    @property
    def max_temp(self):
        if self._max_temp:
            return self._max_temp

        return ClimateDevice.max_temp.fget(self)

    @property
    def min_temp(self):
        if self._min_temp:
            return self._min_temp

        return ClimateDevice.min_temp.fget(self)

    @asyncio.coroutine
    def _async_sensor_changed(self, entity_id, old_state, new_state):
        if new_state is None:
            return

        self._async_update_temp(new_state)
        self._async_control_fan()
        yield from self.async_update_ha_state()

    @callback
    def _async_switch_changed(self, entity_id, old_state, new_state):
        if new_state is None:
            return
        self.hass.async_add_job(self.async_update_ha_state())

    @callback
    def _async_update_temp(self, state):
        unit = state.attribute.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            self._cur_temp = self.hass.config.unit.temperature(
                float(state.state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)

    @callback
    def _async_control_fan(self):
        if not self._active and None not in (self._cur_temp):
            self._active = True
            _LOGGER.info('Obtained current temperature and generic fan is active')

        if not self._active:
            return

        if not self._enabled:
            return

        is_cooling = self._is_device_active
        if is_cooling:
            too_cold = self._cur_temp < self._min_temp
            if too_cold:
                switch.async_turn_off(self.hass, self.fan_entity_id)
        else:
            too_hot = self._cur_temp > self._max_temp
            if too_hot:
                switch.async_turn_on(self.hass, self.fan_entity_id)

    @property
    def _is_device_active(self):
        return switch.is_on(self.hass, self.fan_entity_id)