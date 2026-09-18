"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import type { ReactNode } from "react";

interface SortableGridProps {
  ids: string[];
  onReorder: (activeId: string, overId: string) => void;
  children: ReactNode;
  className?: string;
  label: string;
}

/**
 * Drag-to-reorder wrapper shared by the file grid and the page grid. The pointer sensor
 * needs a few pixels of travel before it activates, otherwise the remove and rotate buttons
 * sitting on each card would swallow their own clicks.
 */
export function SortableGrid({ ids, onReorder, children, className, label }: SortableGridProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (over && active.id !== over.id) onReorder(String(active.id), String(over.id));
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={ids} strategy={rectSortingStrategy}>
        <ul className={className} aria-label={label}>
          {children}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
