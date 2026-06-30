// oxlint-disable max-classes-per-file -- a tagged-error catalog groups classes
// Typed error catalog (errore) for the SDK. The bus is streaming — most runtime
// failures surface via connection status or are dropped (a bad frame on a hot
// topic shouldn't throw) — so these tagged errors are for the request/response
// edges (connect, explicit decode) and for app code building on top of the SDK,
// per the house "errors as values" convention.
import * as errore from "errore";

export class ConnectionError extends errore.createTaggedError({
  name: "ConnectionError",
  message: "Failed to connect to the DimOS gateway",
}) {}

export class DecodeError extends errore.createTaggedError({
  name: "DecodeError",
  message: "Failed to decode a bus message",
}) {}

export class TransportClosed extends errore.createTaggedError({
  name: "TransportClosed",
  message: "The transport is closed",
}) {}
