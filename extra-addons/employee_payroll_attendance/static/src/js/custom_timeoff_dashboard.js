
odoo.define('employee_payroll_attendance.highlight_makeup', function(require) {
    "use strict";
  
    const rpc = require('web.rpc');
    const { patch } = require('web.utils');
    const { onWillStart } = require('@odoo/owl');
    const { CalendarRenderer } = require('@web/views/calendar/calendar_renderer');
  
    patch(CalendarRenderer.prototype, 'employee_payroll_attendance.highlight_makeup_css', {
      setup() {
        this._super.apply(this, arguments);
        this.makeupDays = [];
        this.dayOffDays=[];
        this.makeupDaysAlternate=[];
        onWillStart(async () => {
          const recs_makeup = await rpc.query({
            model: 'work.saturday.schedule',
            method: 'search_read',
            args: [[['makeup_day', '!=', false]], ['makeup_day']],
          });        
          this.makeupDays = recs_makeup.map(r => r.makeup_day);
          console.log('▶ MAKEUP DAYS:', this.makeupDays);
        //   --------------------------------------------------------------
          
          const recs = await rpc.query({
            model: 'work.saturday.schedule',
            method: 'search_read',
            args: [[['day_off', '!=', false]], ['day_off']],
          });
          this.dayOffDays = recs.map(r => r.day_off);
          console.log('▶ DAY OFF DAYS:', this.dayOffDays);
          //----------------------------------------------------------------
          const recs_alternate = await rpc.query({
            model: 'work.saturday.schedule',
            method: 'search_read',
            args: [[['makeup_day_alternate', '!=', false]], ['makeup_day_alternate']],
          });
          this.makeupDaysAlternate = recs_alternate.map(r => r.makeup_day_alternate);
          console.log('▶ makeupDaysAlternate:', this.makeupDaysAlternate);
          if (this.makeupDays.length) {
            
          // 🔥 Tạo style override opacity, filter, màu chữ, background … 
          const rules = this.makeupDays.map(d => `
            /* bật sáng cả ô */
            [data-date="${d}"] {
              opacity: 1 !important;
              filter: none !important;
              background-color: inherit !important;
            }
            /* reset màu số ngày */
            [data-date="${d}"] .fc-day-number {
              color: inherit !important;
              opacity: 1 !important;
              filter: none !important;
            }
          `).join("\n");
          const style = document.createElement('style');
          style.innerHTML = rules;
          document.head.appendChild(style);
          console.log('▶ highlight_makeup CSS injected');
        }
        if (this.makeupDaysAlternate.length) {
            
            // 🔥 Tạo style override opacity, filter, màu chữ, background … 
            const rules = this.makeupDaysAlternate.map(d => `
              /* bật sáng cả ô */
              [data-date="${d}"] {
                opacity: 1 !important;
                filter: none !important;
                background-color: inherit !important;
              }
              /* reset màu số ngày */
              [data-date="${d}"] .fc-day-number {
                color: inherit !important;
                opacity: 1 !important;
                filter: none !important;
              }
            `).join("\n");
            const style = document.createElement('style');
            style.innerHTML = rules;
            document.head.appendChild(style);
            console.log('▶ highlight_makeup CSS injected');
          }
        if (this.dayOffDays.length){
            const rules = this.dayOffDays.map(d => `
                /* ô date="${d}" */
                [data-date="${d}"] {
                  opacity: 1 !important;
                  filter: none !important;
                  background-color: #E9ECEF !important;
                }
                [data-date="${d}"] .fc-day-number {
                    color: inherit !important;
                    opacity: 1 !important;
                    filter: none !important;
                }
              `).join("\n");
              const style = document.createElement('style');
              style.innerHTML = rules;
              document.head.appendChild(style);
              console.log('▶ gray_out_day_off CSS injected');
        }
          
        });
        
      },

    });
  });
  