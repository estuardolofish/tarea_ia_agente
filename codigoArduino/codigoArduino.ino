// Arduino UNO - Botón por Serial para registrar agua
// Envía: "PULSE" cuando se presiona el botón

const int PIN_BOTON = 2;   // Botón entre D2 y GND
const int PIN_LED   = 13;  // LED del Arduino (opcional)

bool estadoAnterior = HIGH;
unsigned long ultimoCambio = 0;
const unsigned long debounceMs = 50;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_BOTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
}

void loop() {
  bool estadoActual = digitalRead(PIN_BOTON);

  if (estadoActual != estadoAnterior) {
    ultimoCambio = millis();
    estadoAnterior = estadoActual;
  }

  if ((millis() - ultimoCambio) > debounceMs) {
    if (estadoActual == LOW) {
      Serial.println("PULSE");

      // Señal visual rápida
      digitalWrite(PIN_LED, HIGH);
      delay(80);
      digitalWrite(PIN_LED, LOW);

      // Espera a soltar para no repetir
      while (digitalRead(PIN_BOTON) == LOW) {
        delay(10);
      }
    }
  }
}