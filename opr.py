import customtkinter as ctk
import os

ctk.set_appearance_mode("Dark")

class RedTeamApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("DRAGON FLY - Ligero")
        self.geometry("800x480")  # Tamaño fijo, sin fullscreen
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Sidebar
        self.sidebar_frame = ctk.CTkFrame(self, width=180)
        self.sidebar_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="DRAGON FLY",
                                       font=ctk.CTkFont(size=16, weight="bold"))
        self.logo_label.pack(pady=10)

        self.btn_inicio = ctk.CTkButton(self.sidebar_frame, text="Inicio", command=self.show_inicio)
        self.btn_inicio.pack(pady=5, padx=10, fill="x")

        # Frame principal
        self.main_frame = ctk.CTkScrollableFrame(self)
        self.main_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        self.show_inicio()

    def limpiar_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def show_inicio(self):
        self.limpiar_main_frame()
        ctk.CTkLabel(self.main_frame, text="Bienvenido a Dragon Fly",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
        ctk.CTkLabel(self.main_frame, text="Selecciona una herramienta del menú lateral.",
                     font=ctk.CTkFont(size=12)).pack(pady=10)

if __name__ == "__main__":
    app = RedTeamApp()
    app.mainloop()
