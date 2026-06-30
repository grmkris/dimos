// Runtime widget registry: map a message TYPE → a React component, so an app can
// visualize its OWN (custom) message types without forking the SDK. The built-in
// dimoscope app wires its panels directly; this is the extensibility seam that
// Part 3's "bring-your-own-topic" example consumes (alongside @dimos/msgs'
// registerType for decoding).
import type { ComponentType } from "react";

export type WidgetProps = { topic: string };

const widgets = new Map<string, ComponentType<WidgetProps>>();

/** Register a component to render a given message type (e.g. "myapp.Telemetry"). */
export function registerWidget(
  type: string,
  component: ComponentType<WidgetProps>
): void {
  widgets.set(type, component);
}

/** The component registered for a message type, or undefined if none. */
export function widgetForType(
  type: string
): ComponentType<WidgetProps> | undefined {
  return widgets.get(type);
}
