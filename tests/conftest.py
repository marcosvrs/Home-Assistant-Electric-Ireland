# pyright: reportMissingImports=false

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


SAMPLE_DATAPOINTS = [
    {"consumption": 0.222, "cost": 0.04, "intervalEnd": 1774224000},
    {"consumption": 0.198, "cost": 0.04, "intervalEnd": 1774227600},
    {"consumption": 0.173, "cost": 0.03, "intervalEnd": 1774231200},
    {"consumption": 0.165, "cost": 0.03, "intervalEnd": 1774234800},
    {"consumption": 0.149, "cost": 0.03, "intervalEnd": 1774238400},
    {"consumption": 0.138, "cost": 0.03, "intervalEnd": 1774242000},
    {"consumption": 0.155, "cost": 0.04, "intervalEnd": 1774245600},
    {"consumption": 0.212, "cost": 0.05, "intervalEnd": 1774249200},
    {"consumption": 0.305, "cost": 0.08, "intervalEnd": 1774252800},
    {"consumption": 0.492, "cost": 0.14, "intervalEnd": 1774256400},
    {"consumption": 0.684, "cost": 0.2, "intervalEnd": 1774260000},
    {"consumption": 0.918, "cost": 0.28, "intervalEnd": 1774263600},
    {"consumption": 1.102, "cost": 0.34, "intervalEnd": 1774267200},
    {"consumption": 1.238, "cost": 0.39, "intervalEnd": 1774270800},
    {"consumption": 1.356, "cost": 0.43, "intervalEnd": 1774274400},
    {"consumption": 1.478, "cost": 0.48, "intervalEnd": 1774278000},
    {"consumption": 1.592, "cost": 0.52, "intervalEnd": 1774281600},
    {"consumption": 1.704, "cost": 0.57, "intervalEnd": 1774285200},
    {"consumption": 1.845, "cost": 0.63, "intervalEnd": 1774288800},
    {"consumption": 2.012, "cost": 0.7, "intervalEnd": 1774292400},
    {"consumption": 2.256, "cost": 0.78, "intervalEnd": 1774296000},
    {"consumption": 2.588, "cost": 0.88, "intervalEnd": 1774299600},
    {"consumption": 2.942, "cost": 0.99, "intervalEnd": 1774303200},
    {"consumption": 3.417, "cost": 1.1, "intervalEnd": 1774306800},
]


@pytest.fixture
def mock_config_entry():
    return MockConfigEntry(
        domain="electric_ireland_insights",
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "951785073",
        },
        unique_id="951785073",
    )


@pytest.fixture
def mock_api():
    api_mock = AsyncMock()
    api_instance = AsyncMock()
    api_instance.fetch_day_range = AsyncMock(return_value=(SAMPLE_DATAPOINTS, None))
    api_instance.validate_credentials = AsyncMock(
        return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
    )
    api_mock.return_value = api_instance

    with patch(
        "custom_components.electric_ireland_insights.api.ElectricIrelandAPI",
        new=api_mock,
        create=True,
    ):
        yield api_mock


@pytest.fixture
def mock_setup_entry():
    with patch(
        "custom_components.electric_ireland_insights.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as setup_mock:
        yield setup_mock
