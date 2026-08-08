"""
Helper dialog runner for visualize_subzone_3d custom vector configuration window.
Opens a single unified dialog window containing file picker, display name, geometry style, color, elevation offset, and Add button.
"""

import sys
import os
import json
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as fd
import tkinter.messagebox as mb


def run_add_vector_dialog():
    root = tk.Tk()
    root.title("Add Custom Vector Layer")
    root.geometry("460x450")
    root.attributes("-topmost", True)
    root.configure(bg="#2d2d30")

    lbl_style = {"bg": "#2d2d30", "fg": "#ffffff", "font": ("Segoe UI", 10, "bold")}

    # 1. File Selection Row (Text field + Browse... button inside dialog!)
    tk.Label(root, text="1. Select Vector File (.shp / .geojson):", **lbl_style).pack(anchor="w", padx=20, pady=(15, 5))
    f_file = tk.Frame(root, bg="#2d2d30")
    f_file.pack(fill="x", padx=20)

    e_file = tk.Entry(f_file, font=("Segoe UI", 9))
    e_file.pack(side="left", fill="x", expand=True, padx=(0, 5))

    def on_browse_file():
        path = fd.askopenfilename(
            parent=root,
            title="Select Custom Vector File",
            filetypes=[("Vector Files", "*.shp;*.geojson"), ("All Files", "*.*")],
        )
        if path:
            e_file.delete(0, tk.END)
            e_file.insert(0, path)
            base_name = os.path.splitext(os.path.basename(path))[0]
            if not e_name.get() or e_name.get() == "New Vector Layer":
                e_name.delete(0, tk.END)
                e_name.insert(0, base_name)
            if "fire" in base_name.lower() or "boundary" in base_name.lower() or "zone" in base_name.lower():
                v_type.set("Area")
                cb_color.set("Orange" if "fire" in base_name.lower() else "Yellow")
                e_offset.delete(0, tk.END)
                e_offset.insert(0, "0.0")
            elif "line" in base_name.lower() or "power" in base_name.lower() or "ug" in base_name.lower():
                v_type.set("Polyline")
                cb_color.set("Red" if "ug" in base_name.lower() else "Yellow")
                e_offset.delete(0, tk.END)
                e_offset.insert(0, "0.0" if "ug" in base_name.lower() else "+30.0")

    btn_browse = tk.Button(
        f_file, text=" Browse... ", bg="#444444", fg="white", font=("Segoe UI", 9, "bold"), command=on_browse_file, relief="flat"
    )
    btn_browse.pack(side="right")

    # 2. Display Name
    tk.Label(root, text="2. Layer Display Name:", **lbl_style).pack(anchor="w", padx=20, pady=(12, 5))
    e_name = tk.Entry(root, font=("Segoe UI", 10))
    e_name.insert(0, "New Vector Layer")
    e_name.pack(fill="x", padx=20)

    # 3. Geometry Type (Polyline vs Area)
    tk.Label(root, text="3. Geometry Style:", **lbl_style).pack(anchor="w", padx=20, pady=(12, 5))
    v_type = tk.StringVar(value="Polyline")
    f_type = tk.Frame(root, bg="#2d2d30")
    f_type.pack(anchor="w", padx=20)
    tk.Radiobutton(
        f_type,
        text="Polyline (3D Cable/Line)",
        variable=v_type,
        value="Polyline",
        bg="#2d2d30",
        fg="#ffffff",
        selectcolor="#444444",
        activebackground="#2d2d30",
        activeforeground="#ffffff",
        font=("Segoe UI", 9),
    ).pack(side="left")
    tk.Radiobutton(
        f_type,
        text="Area (Polygon Zone)",
        variable=v_type,
        value="Area",
        bg="#2d2d30",
        fg="#ffffff",
        selectcolor="#444444",
        activebackground="#2d2d30",
        activeforeground="#ffffff",
        font=("Segoe UI", 9),
    ).pack(side="left", padx=15)

    # 4. Display Color
    tk.Label(root, text="4. Display Color:", **lbl_style).pack(anchor="w", padx=20, pady=(12, 5))
    cb_color = ttk.Combobox(
        root, values=["Yellow", "Red", "Cyan", "Green", "Magenta", "Orange", "White", "Gray"], font=("Segoe UI", 10)
    )
    cb_color.set("Yellow")
    cb_color.pack(fill="x", padx=20)

    # 5. Elevation Offset
    tk.Label(root, text="5. Elevation Offset (ft from ground):", **lbl_style).pack(anchor="w", padx=20, pady=(12, 5))
    e_offset = tk.Entry(root, font=("Segoe UI", 10))
    e_offset.insert(0, "0.0")
    e_offset.pack(fill="x", padx=20)

    res = {}

    def on_ok():
        file_path = e_file.get().strip()
        if not file_path or not os.path.exists(file_path):
            mb.showwarning("File Missing", "Please select a valid vector file (.shp / .geojson).", parent=root)
            return
        res["path"] = file_path
        res["name"] = e_name.get().strip() or os.path.splitext(os.path.basename(file_path))[0]
        res["type"] = v_type.get()
        res["color"] = cb_color.get()
        res["offset"] = e_offset.get().strip() or "0.0"
        root.destroy()

    btn_ok = tk.Button(
        root,
        text="  + Add Layer  ",
        bg="#007acc",
        fg="white",
        font=("Segoe UI", 10, "bold"),
        command=on_ok,
        relief="flat",
        padx=15,
        pady=6,
    )
    btn_ok.pack(pady=20)

    root.mainloop()
    print(json.dumps(res))


if __name__ == "__main__":
    run_add_vector_dialog()
