// Script global para manejar todas las confirmaciones modales
// Este archivo debe ser incluido en templates que necesiten confirmaciones

document.addEventListener('DOMContentLoaded', function () {

    // === VACACIONES: Cancelar solicitud ===
    document.querySelectorAll('.cancel-vacation-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const form = this.closest('form');
            const estado = this.dataset.estado;
            const fechas = this.dataset.fechas;

            const title = estado === 'pendiente' ? 'Cancelar Solicitud' : 'Solicitar Cancelación';
            const message = estado === 'pendiente'
                ? `¿Estás seguro de que deseas cancelar tu solicitud de vacaciones (${fechas})?`
                : `¿Estás seguro de que deseas solicitar la cancelación de tus vacaciones aprobadas (${fechas})?\n\nEsta acción requerirá aprobación.`;

            showConfirmModal(title, message, () => submitFormWithConfirm(form), 'danger', 'Confirmar');
        });
    });

    // === BAJAS: Cancelar solicitud ===
    document.querySelectorAll('.cancel-baja-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const form = this.closest('form');
            const fechas = this.dataset.fechas;

            showConfirmModal(
                'Cancelar Solicitud de Baja',
                `¿Estás seguro de que deseas cancelar tu solicitud de baja/ausencia (${fechas})?`,
                () => submitFormWithConfirm(form),
                'danger',
                'Confirmar'
            );
        });
    });

    // === FICHAJES: Eliminar fichaje ===
    document.querySelectorAll('.delete-my-fichaje-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const form = this.closest('form');
            const fecha = this.dataset.fecha;

            showConfirmModal(
                'Eliminar Fichaje',
                `¿Estás seguro de que deseas eliminar tu fichaje del ${fecha}?\n\nEsta acción no se puede deshacer.`,
                () => submitFormWithConfirm(form),
                'danger',
                'Eliminar'
            );
        });
    });

    // === APROBAR SOLICITUDES: Aprobar ===
    document.querySelectorAll('.approve-request-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const form = this.closest('form');
            const tipo = this.dataset.tipo; // 'vacaciones' o 'baja'
            const usuario = this.dataset.usuario;
            const fechas = this.dataset.fechas;
            const dias = this.dataset.dias;

            showConfirmModal(
                `Aprobar ${tipo === 'vacaciones' ? 'Vacaciones' : 'Ausencia'}`,
                `¿Aprobar la solicitud de ${tipo} de "${usuario}"?\n\nPeríodo: ${fechas}\nDías: ${dias}`,
                () => submitFormWithConfirm(form),
                'success',
                'Aprobar'
            );
        });
    });

    // === APROBAR SOLICITUDES: Rechazar ===
    document.querySelectorAll('.reject-request-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const form = this.closest('form');
            const tipo = this.dataset.tipo;
            const usuario = this.dataset.usuario;
            const fechas = this.dataset.fechas;

            showConfirmModal(
                `Rechazar ${tipo === 'vacaciones' ? 'Vacaciones' : 'Ausencia'}`,
                `¿Estás seguro de que deseas rechazar la solicitud de ${tipo} de "${usuario}"?\n\nPeríodo: ${fechas}\n\nEsta acción notificará al empleado.`,
                () => submitFormWithConfirm(form),
                'danger',
                'Rechazar'
            );
        });
    });
});
