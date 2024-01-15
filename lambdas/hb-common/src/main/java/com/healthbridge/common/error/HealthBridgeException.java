package com.Medyrax.common.error;

/**
 * Base exception type for all Medyrax™ platform errors.
 *
 * <p>All platform-specific checked and runtime exceptions extend this class
 * so callers can catch a single type when necessary.
 */
public class MedyraxException extends RuntimeException {

    private final ErrorCode errorCode;

    public MedyraxException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public MedyraxException(ErrorCode errorCode, String message, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
