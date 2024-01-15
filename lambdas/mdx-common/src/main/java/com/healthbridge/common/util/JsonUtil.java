package com.Medyrax.common.util;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.Medyrax.common.error.ErrorCode;
import com.Medyrax.common.error.MedyraxException;

import java.io.IOException;

/**
 * Shared Jackson {@link ObjectMapper} utility for the Medyrax™ platform.
 *
 * <p>A single, pre-configured {@code ObjectMapper} instance is shared across
 * all Lambda handlers and utilities to avoid the overhead of creating a new
 * instance per invocation (ObjectMapper is thread-safe once configured).
 */
public final class JsonUtil {

    /**
     * Singleton, thread-safe {@link ObjectMapper} configured for:
     * <ul>
     *   <li>ISO-8601 date/time serialization (not timestamps)</li>
     *   <li>Java time types via {@link JavaTimeModule}</li>
     *   <li>Non-null / non-empty field inclusion (callers choose their own strategy)</li>
     * </ul>
     */
    public static final ObjectMapper MAPPER;

    static {
        MAPPER = new ObjectMapper();
        MAPPER.registerModule(new JavaTimeModule());
        MAPPER.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }

    private JsonUtil() {}

    /**
     * Serializes {@code object} to a JSON string.
     *
     * @throws MedyraxException with {@link ErrorCode#INTERNAL_SERVER_ERROR}
     *         if serialization fails
     */
    public static String toJson(Object object) {
        try {
            return MAPPER.writeValueAsString(object);
        } catch (IOException e) {
            throw new MedyraxException(ErrorCode.INTERNAL_SERVER_ERROR,
                    "JSON serialization failed: " + e.getMessage(), e);
        }
    }

    /**
     * Deserializes a JSON string to the given type.
     *
     * @throws MedyraxException with {@link ErrorCode#INTERNAL_SERVER_ERROR}
     *         if deserialization fails
     */
    public static <T> T fromJson(String json, Class<T> clazz) {
        try {
            return MAPPER.readValue(json, clazz);
        } catch (IOException e) {
            throw new MedyraxException(ErrorCode.INTERNAL_SERVER_ERROR,
                    "JSON deserialization failed for type " + clazz.getSimpleName()
                    + ": " + e.getMessage(), e);
        }
    }

    /**
     * Parses a JSON string into a {@link JsonNode} tree.
     *
     * @throws MedyraxException with {@link ErrorCode#INTERNAL_SERVER_ERROR}
     *         if parsing fails
     */
    public static JsonNode parseTree(String json) {
        try {
            return MAPPER.readTree(json);
        } catch (IOException e) {
            throw new MedyraxException(ErrorCode.INTERNAL_SERVER_ERROR,
                    "JSON tree parsing failed: " + e.getMessage(), e);
        }
    }
}
