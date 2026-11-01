"use client";

import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, rectSortingStrategy, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ReactNode } from "react";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { IconButton } from "./IconButton";

function Row({ id, label, index, count, move, className = "", children }: { id: string; label: string; index: number; count: number; move: (from: number, to: number) => void; className?: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  // dnd-kit positions the dragged row with live coordinates, which only a style can carry.
  const position = { transform: CSS.Transform.toString(transform), transition };
  return (
    <li ref={setNodeRef} {...{ style: position }} className={`rounded-md ${className} ${isDragging ? "bg-surface-sunken shadow-raised" : ""}`}>
      <div className="flex items-center gap-1">
        <button type="button" aria-label={t("sortable.drag", { label })} className="focus-ring cursor-grab rounded-sm p-1 text-ink-muted" {...attributes} {...listeners}>
          <Icon name="grip" />
        </button>
        <div className="min-w-0 flex-1">{children}</div>
        <IconButton icon="moveUp" label={t("sortable.up", { label })} tooltip={false} disabled={index === 0} onClick={() => move(index, index - 1)} />
        <IconButton icon="moveDown" label={t("sortable.down", { label })} tooltip={false} disabled={index === count - 1} onClick={() => move(index, index + 1)} />
      </div>
    </li>
  );
}

export interface SortableItem {
  id: string;
  label: string;
  content: ReactNode;
  className?: string;
}

/** A list reordered by dragging, by keyboard on the handle, or with the arrow buttons. */
export function Sortable({ label, items, layout = "list", onReorder }: { label: string; items: readonly SortableItem[]; layout?: "list" | "grid"; onReorder: (ids: string[]) => void }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const ids = items.map((item) => item.id);
  const move = (from: number, to: number) => onReorder(arrayMove(ids, from, to));
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) move(ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
  };
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={layout === "grid" ? rectSortingStrategy : verticalListSortingStrategy}>
        <ul aria-label={label} className={layout === "grid" ? "grid grid-cols-3 gap-4" : "flex flex-col gap-px"}>
          {items.map((item, index) => (
            <Row key={item.id} id={item.id} label={item.label} index={index} count={items.length} move={move} {...(item.className ? { className: item.className } : {})}>
              {item.content}
            </Row>
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
