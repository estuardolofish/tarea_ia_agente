#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import serial
from serial.tools import list_ports


# =========================
# Persistencia (archivo JSON)
# =========================

def cargar_json(ruta: str) -> dict:
    if not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(ruta: str, datos: dict) -> None:
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# =========================
# Serial (Arduino)
# =========================

def listar_puertos_serial() -> List[Tuple[str, str]]:
    puertos = list(list_ports.comports())
    return [(p.device, p.description) for p in puertos]


# =========================
# Modelos
# =========================

@dataclass
class EntradaDelDia:
    fecha: str          # YYYY-MM-DD
    hora: int           # 0-23
    agua_ml: int        # total consumido del día
    actividad: str      # sedentario | normal | ejercicio


# =========================
# Agente
# =========================

class AgenteHidratacion:
    def __init__(self, ruta_bd: str = "bd_hidratacion.json"):
        self.ruta_bd = ruta_bd
        self.bd = self._cargar_bd()
        self.carnet_activo: Optional[str] = None  # sesión actual

    def _cargar_bd(self) -> dict:
        bd = cargar_json(self.ruta_bd)
        if "usuarios" not in bd:
            bd["usuarios"] = {}
        if "registros" not in bd:
            bd["registros"] = {}
        return bd

    def _guardar_bd(self) -> None:
        guardar_json(self.ruta_bd, self.bd)

    # -------- Sensor (software) --------
    def leer_entrada_del_dia(self) -> EntradaDelDia:
        hoy = date.today().isoformat()
        print("\nIngreso de datos del día")
        print(f"Fecha (automática): {hoy}")

        hora = self._pedir_int("Hora actual (0-23): ", minimo=0, maximo=23)

        actividad = self._pedir_opcion(
            "Actividad [1] sedentario [2] normal [3] ejercicio: ",
            {"1": "sedentario", "2": "normal", "3": "ejercicio"}
        )

        agua_a_sumar = self._pedir_int("Agua a registrar en ml (por ejemplo 250): ", minimo=0, maximo=10000)

        total_hoy_actual = self._obtener_agua_hoy(self.carnet_activo, hoy)
        total_nuevo = total_hoy_actual + agua_a_sumar

        return EntradaDelDia(
            fecha=hoy,
            hora=hora,
            actividad=actividad,
            agua_ml=total_nuevo
        )

    # -------- Decisión inteligente --------
    def calcular_meta_agua_ml(self, actividad: str) -> int:
        base = 2000
        extra = 0
        if actividad == "sedentario":
            extra = 0
        elif actividad == "normal":
            extra = 300
        elif actividad == "ejercicio":
            extra = 700
        return base + extra

    def calcular_prioridad(self, hora: int, faltante: int) -> str:
        if faltante <= 0:
            return "OK"
        if faltante <= 300:
            return "BAJA"
        if faltante <= 700:
            return "MEDIA"
        if hora >= 19:
            return "ALTA"
        return "ALTA"

    def construir_recomendacion(self, meta: int, consumido: int, faltante: int, hora: int, prioridad: str) -> str:
        if faltante <= 0:
            return (
                f"Meta del día: {meta} ml.\n"
                f"Consumo actual: {consumido} ml.\n"
                "Ya cumpliste tu meta de agua hoy."
            )

        texto = (
            f"Meta del día: {meta} ml.\n"
            f"Consumo actual: {consumido} ml.\n"
            f"Te faltan: {faltante} ml.\n"
            f"Prioridad: {prioridad}.\n"
        )

        if hora >= 21:
            texto += "Ya es tarde. Toma una porción moderada ahora y otra en 45 minutos.\n"
        elif hora >= 19:
            texto += "Queda poco tiempo del día. Conviene repartir el agua en 2 o 3 tomas.\n"
        else:
            texto += "Vas a tiempo. Reparte el faltante en varias tomas durante la tarde.\n"

        return texto

    def plan_simple(self, hora: int, faltante: int) -> List[str]:
        if faltante <= 0:
            return []

        lineas: List[str] = []

        if hora >= 21:
            primera = min(300, faltante)
            restante = max(0, faltante - primera)
            lineas.append(f"- Ahora: {primera} ml")
            if restante > 0:
                lineas.append(f"- En 45 minutos: {min(250, restante)} ml")
            return lineas

        tomas = 2
        if faltante > 900:
            tomas = 3

        por_toma = max(200, faltante // tomas)
        for i in range(tomas):
            lineas.append(f"- Toma {i+1}: {por_toma} ml")
        return lineas

    # -------- Actuador --------
    def registrar_dia(self, entrada: EntradaDelDia) -> None:
        carnet = self.carnet_activo
        if carnet is None:
            raise RuntimeError("No hay usuario activo.")

        if carnet not in self.bd["registros"]:
            self.bd["registros"][carnet] = {}

        self.bd["registros"][carnet][entrada.fecha] = {
            "agua_ml": int(entrada.agua_ml),
            "actividad": str(entrada.actividad),
            "ultima_hora": int(entrada.hora),
        }
        self._guardar_bd()

    # =========================
    # Menú y sesión
    # =========================

    def ejecutar(self) -> None:
        while True:
            print("\n==============================")
            print("AGENTE: COACH DE HIDRATACION")
            print("==============================")
            print("Usuario activo:", self._usuario_activo_texto())
            print("------------------------------")
            print("1) Iniciar sesion / Elegir usuario")
            print("2) Registrar agua manual (usuario activo)")
            print("3) Ver resumen de hoy (usuario activo)")
            print("4) Ver historial (usuario activo)")
            print("5) Configurar ml por boton (usuario activo)")
            print("6) Modo Arduino (usuario activo)")
            print("7) Cambiar usuario")
            print("8) Salir")
            opcion = input("Elige una opcion: ").strip()

            if opcion == "1":
                self.iniciar_o_elegir_usuario()
            elif opcion == "2":
                self._requerir_usuario_activo()
                self.op_registrar_agua()
            elif opcion == "3":
                self._requerir_usuario_activo()
                self.op_resumen_hoy()
            elif opcion == "4":
                self._requerir_usuario_activo()
                self.op_historial()
            elif opcion == "5":
                self.op_configurar_ml_por_boton()
            elif opcion == "6":
                self.op_modo_arduino()
            elif opcion == "7":
                self.iniciar_o_elegir_usuario()
            elif opcion == "8":
                print("Saliendo...")
                break
            else:
                print("Opcion invalida. Intenta de nuevo.")

    def iniciar_o_elegir_usuario(self) -> None:
        print("\n--- Usuario ---")
        carnet = input("Ingresa tu carnet (o ID): ").strip()

        if not carnet:
            print("Carnet vacio. No se cambio el usuario.")
            return

        if carnet not in self.bd["usuarios"]:
            nombre = input("Usuario nuevo. Ingresa tu nombre: ").strip()
            if not nombre:
                print("Nombre vacio. No se creo el usuario.")
                return

            ml_por_boton = self._pedir_int("Configura ml por boton (ej. 250): ", minimo=1, maximo=2000)

            self.bd["usuarios"][carnet] = {"nombre": nombre, "ml_por_boton": ml_por_boton}
            self.bd["registros"].setdefault(carnet, {})
            self._guardar_bd()
            print("Usuario creado.")
        else:
            # Si es viejo y no tiene ml_por_boton, se lo ponemos
            if "ml_por_boton" not in self.bd["usuarios"][carnet]:
                self.bd["usuarios"][carnet]["ml_por_boton"] = 250
                self._guardar_bd()

        self.carnet_activo = carnet
        print(f"Usuario activo: {self.bd['usuarios'][carnet]['nombre']} ({carnet})")
        print(f"ml por boton: {self.bd['usuarios'][carnet]['ml_por_boton']}")

    def op_registrar_agua(self) -> None:
        entrada = self.leer_entrada_del_dia()

        meta = self.calcular_meta_agua_ml(entrada.actividad)
        faltante = meta - entrada.agua_ml
        prioridad = self.calcular_prioridad(entrada.hora, faltante)
        recomendacion = self.construir_recomendacion(meta, entrada.agua_ml, faltante, entrada.hora, prioridad)
        plan = self.plan_simple(entrada.hora, faltante)

        self.registrar_dia(entrada)

        print("\n--- Resultado ---")
        print(recomendacion)
        if plan:
            print("Plan sugerido:")
            for linea in plan:
                print(linea)

    def op_resumen_hoy(self) -> None:
        carnet = self.carnet_activo
        hoy = date.today().isoformat()

        reg = self.bd["registros"].get(carnet, {}).get(hoy)
        nombre = self.bd["usuarios"][carnet]["nombre"]

        print("\n--- Resumen de hoy ---")
        print(f"Usuario: {nombre} ({carnet})")
        print(f"Fecha: {hoy}")

        if not reg:
            print("Aun no hay registro de hoy.")
            print("Usa la opcion 2 para registrar agua manual o la opcion 6 para Arduino.")
            return

        actividad = reg["actividad"]
        consumido = int(reg["agua_ml"])
        hora = int(reg.get("ultima_hora", 12))

        meta = self.calcular_meta_agua_ml(actividad)
        faltante = meta - consumido
        prioridad = self.calcular_prioridad(hora, faltante)
        recomendacion = self.construir_recomendacion(meta, consumido, faltante, hora, prioridad)

        print(recomendacion)

    def op_historial(self) -> None:
        carnet = self.carnet_activo
        nombre = self.bd["usuarios"][carnet]["nombre"]
        registros = self.bd["registros"].get(carnet, {})

        print("\n--- Historial ---")
        print(f"Usuario: {nombre} ({carnet})")

        if not registros:
            print("No hay registros aun.")
            return

        fechas = sorted(registros.keys())
        print("Fecha        | Agua(ml) | Actividad")
        print("------------------------------------")
        for f in fechas:
            r = registros[f]
            print(f"{f} | {str(r['agua_ml']).rjust(7)} | {r['actividad']}")

    def op_configurar_ml_por_boton(self) -> None:
        self._requerir_usuario_activo()
        carnet = self.carnet_activo

        actual = int(self.bd["usuarios"][carnet].get("ml_por_boton", 250))
        print("\n--- Configuracion ml por boton ---")
        print(f"Valor actual: {actual} ml")

        nuevo = self._pedir_int("Nuevo valor (ml): ", minimo=1, maximo=2000)
        self.bd["usuarios"][carnet]["ml_por_boton"] = nuevo
        self._guardar_bd()

        print("Configuracion guardada.")

    def op_modo_arduino(self) -> None:
        self._requerir_usuario_activo()

        puertos = listar_puertos_serial()
        if not puertos:
            print("\nNo se detectaron puertos seriales.")
            print("Conecta el Arduino por USB y vuelve a intentar.")
            return

        print("\n--- Puertos disponibles ---")
        for i, (dev, desc) in enumerate(puertos, start=1):
            print(f"{i}) {dev} - {desc}")

        idx = self._pedir_int("Elige el numero de puerto: ", minimo=1, maximo=len(puertos))
        puerto = puertos[idx - 1][0]

        baud = 9600
        carnet = self.carnet_activo
        ml_por_boton = int(self.bd["usuarios"][carnet].get("ml_por_boton", 250))

        print("\n--- Modo Arduino activo ---")
        print("Presiona el boton para registrar agua.")
        print("Para salir de este modo: presiona Ctrl + C.\n")

        try:
            with serial.Serial(puerto, baud, timeout=0.2) as ser:
                time.sleep(1.5)

                while True:
                    linea = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not linea:
                        continue

                    if linea == "PULSE":
                        self._registrar_desde_arduino(ml_por_boton)
                    else:
                        # Si quieres ver lo que manda Arduino, descomenta:
                        # print("Serial:", linea)
                        pass

        except KeyboardInterrupt:
            print("\nSaliendo del modo Arduino...")
        except Exception as e:
            print(f"\nError en modo Arduino: {e}")

    def _registrar_desde_arduino(self, ml_por_boton: int) -> None:
        carnet = self.carnet_activo
        hoy = date.today().isoformat()
        hora = int(datetime.now().hour)

        # Si hoy no existe registro, se crea con actividad "normal"
        actividad = self._actividad_hoy(carnet, hoy)

        agua_actual = self._obtener_agua_hoy(carnet, hoy)
        agua_nueva = agua_actual + ml_por_boton

        entrada = EntradaDelDia(
            fecha=hoy,
            hora=hora,
            agua_ml=agua_nueva,
            actividad=actividad
        )

        self.registrar_dia(entrada)

        meta = self.calcular_meta_agua_ml(actividad)
        faltante = meta - agua_nueva
        prioridad = self.calcular_prioridad(hora, faltante)
        recomendacion = self.construir_recomendacion(meta, agua_nueva, faltante, hora, prioridad)

        print("\nRegistro recibido desde Arduino.")
        print(f"Se sumaron {ml_por_boton} ml.")
        print(recomendacion)

    # =========================
    # Helpers
    # =========================

    def _usuario_activo_texto(self) -> str:
        if not self.carnet_activo:
            return "Ninguno"
        u = self.bd["usuarios"].get(self.carnet_activo, {})
        nombre = u.get("nombre", "Desconocido")
        return f"{nombre} ({self.carnet_activo})"

    def _actividad_hoy(self, carnet: str, hoy: str) -> str:
        reg = self.bd["registros"].get(carnet, {}).get(hoy)
        if reg and "actividad" in reg:
            return reg["actividad"]
        return "normal"

    def _obtener_agua_hoy(self, carnet: str, hoy: str) -> int:
        reg = self.bd["registros"].get(carnet, {}).get(hoy)
        if not reg:
            return 0
        return int(reg.get("agua_ml", 0))

    def _requerir_usuario_activo(self) -> None:
        if not self.carnet_activo:
            raise RuntimeError("No hay usuario activo. Primero usa la opcion 1 para iniciar sesion.")

    def _pedir_int(self, mensaje: str, minimo: int, maximo: int) -> int:
        while True:
            valor = input(mensaje).strip()
            try:
                n = int(valor)
                if n < minimo or n > maximo:
                    print(f"Valor fuera de rango. Debe estar entre {minimo} y {maximo}.")
                    continue
                return n
            except ValueError:
                print("Ingresa un numero valido.")

    def _pedir_opcion(self, mensaje: str, mapa: Dict[str, str]) -> str:
        while True:
            valor = input(mensaje).strip()
            if valor in mapa:
                return mapa[valor]
            print("Opcion invalida. Intenta de nuevo.")


# =========================
# Main
# =========================

def main():
    agente = AgenteHidratacion(ruta_bd="bd_hidratacion.json")
    agente.ejecutar()


if __name__ == "__main__":
    main()