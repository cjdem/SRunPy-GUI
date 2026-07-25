"""Domain errors shared by the CLI, desktop UI, and background services."""


class SrunError(Exception):
    """Base class for errors that can be presented safely to a user."""

    code = "srun_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GatewayUnavailableError(SrunError):
    """The configured gateway could not be reached."""

    code = "gateway_unavailable"


class RequestTimeoutError(GatewayUnavailableError):
    """A gateway request exceeded its configured deadline."""

    code = "request_timeout"


class TLSVerificationError(GatewayUnavailableError):
    """The gateway certificate could not be verified."""

    code = "tls_verification_failed"


class GatewayProtocolError(SrunError):
    """The gateway returned a malformed or unsupported response."""

    code = "gateway_protocol_error"


class AlreadyOnlineError(SrunError):
    """A login was requested for a connection that is already online."""

    code = "already_online"


class NotOnlineError(SrunError):
    """A logout was requested for a connection that is not online."""

    code = "not_online"


class AuthenticationRejectedError(SrunError):
    """The gateway rejected the supplied account credentials."""

    code = "authentication_rejected"
